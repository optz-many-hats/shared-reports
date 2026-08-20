"""CLI entry point for the concept/topic test harness.

Usage:
    python -m harness list-agents --env prod --instance <iid>
    python -m harness extract --app-id <uuid> --entities entities.json --env prod --instance <iid>
    python -m harness create-topic --name "Churn & Retention" --entities entities.json --env prod --instance <iid>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import client, clustering, graph

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
GRAPH_PATH = OUTPUT_DIR / "concept_graph.json"
TOPICS_DIR = OUTPUT_DIR / "topics"


def cmd_list_agents(args: argparse.Namespace) -> None:
    agents = client.list_agents(args.env, args.instance)
    for a in agents:
        aid = a.get("id", a.get("agent_id", "?"))
        name = a.get("name", "?")
        human_id = a.get("human_readable_agent_id", a.get("agent_id_slug", ""))
        active = a.get("is_active", True)
        status = "active" if active else "inactive"
        print(f"  {aid}  {name}  (@{human_id})  [{status}]")


def cmd_extract(args: argparse.Namespace) -> None:
    """Run the Concept Extractor agent."""
    entities_path = Path(args.entities)
    if not entities_path.exists():
        print(f"Error: entities file not found: {entities_path}", file=sys.stderr)
        sys.exit(1)

    entities = json.loads(entities_path.read_text())
    print(f"Loaded entities from {entities_path}", file=sys.stderr)

    parameters = {
        "app_id": args.app_id,
        "metadata_image": json.dumps(entities),
        "focus": args.focus or "all",
    }
    if args.hints:
        parameters["admin_hints"] = args.hints

    # Load existing graph for existing_concepts
    if GRAPH_PATH.exists():
        existing = graph.ConceptGraph.load(GRAPH_PATH)
        concepts = existing.get_concepts()
        if concepts:
            parameters["existing_concepts"] = json.dumps(
                [{"name": c.name, "description": c.description} for c in concepts]
            )
            print(
                f"Loaded existing graph: {existing.summary()}",
                file=sys.stderr,
            )
    else:
        existing = graph.ConceptGraph()

    print(f"\nExecuting Concept Extractor ({args.agent_id})...\n", file=sys.stderr)
    result = client.execute_agent(
        args.agent_id,
        parameters,
        args.env,
        args.instance,
    )

    output = result.get("output")
    if not output:
        print("Error: no parseable output from agent.", file=sys.stderr)
        print(f"Raw text:\n{result.get('raw_text', '')[:2000]}", file=sys.stderr)
        sys.exit(1)

    # Merge into graph
    existing.add_from_extraction(output)
    existing.save(GRAPH_PATH)
    print(f"\nGraph saved to {GRAPH_PATH}", file=sys.stderr)
    print(f"Graph: {existing.summary()}", file=sys.stderr)

    # Print summary
    summary = output.get("summary", {})
    print(f"\nExtraction summary:", file=sys.stderr)
    for k, v in summary.items():
        print(f"  {k}: {v}", file=sys.stderr)

    # Print follow-up questions
    follow_ups = output.get("follow_up_questions", [])
    if follow_ups:
        print(f"\nFollow-up questions:", file=sys.stderr)
        for fq in follow_ups:
            print(f"  - {fq['question']}", file=sys.stderr)


def _run_topic_checklist(
    topic_name: str,
    topic_desc: str,
    g: graph.ConceptGraph,
    entities: dict,
    args: argparse.Namespace,
    auto: bool = False,
) -> dict | None:
    """Run the 8-step Topic Creator checklist for a single topic.

    Args:
        topic_name: Name for step 1 auto-answer.
        topic_desc: Description for step 1 auto-answer.
        g: Concept graph to pass as context.
        entities: App entities dict.
        args: CLI args (agent_id, app_id, env, instance).
        auto: If True, accept pre-selections without human input.

    Returns:
        The topic data dict, or None on failure.
    """
    checklist_state: dict[str, dict] = {}

    for step in range(1, 9):
        print(f"  Step {step}/8...", end="", file=sys.stderr, flush=True)

        parameters = {
            "app_id": args.app_id or "test",
            "current_step": str(step),
            "checklist_state": json.dumps(checklist_state),
            "graph_context": g.as_graph_context(),
            "app_entities": json.dumps(entities),
        }

        try:
            result = client.execute_agent(
                args.agent_id,
                parameters,
                args.env,
                args.instance,
            )
        except Exception as e:
            print(f" ERROR: {e}", file=sys.stderr)
            return None

        output = result.get("output")
        if not output:
            print(f" no output", file=sys.stderr)
            return None

        question = output.get("question", "?")
        q_type = output.get("question_type", "free_text")
        options = output.get("options", [])

        if auto:
            # Auto-accept mode
            if step == 1:
                # Step 1 is always free text: domain name + description
                checklist_state[str(step)] = {
                    "question": question,
                    "answer": f"{topic_name}. {topic_desc}",
                }
                print(f" -> {topic_name}", file=sys.stderr)
            elif q_type == "free_text":
                checklist_state[str(step)] = {
                    "question": question,
                    "answer": "Accept defaults.",
                }
                print(" -> defaults", file=sys.stderr)
            elif q_type == "preset_choice":
                # Pick the pre-selected or the second option (moderate)
                preselected = [o for o in options if o.get("pre_selected")]
                if not preselected and len(options) >= 2:
                    preselected = [options[1]]  # moderate is usually index 1
                elif not preselected and options:
                    preselected = [options[0]]
                checklist_state[str(step)] = {
                    "question": question,
                    "selected": preselected,
                }
                labels = [s.get("label", "?") for s in preselected]
                print(f" -> {', '.join(labels)}", file=sys.stderr)
            else:
                # multiple_choice / multiple_choice_with_custom
                selected = [o for o in options if o.get("pre_selected")]
                if not selected:
                    # If nothing pre-selected, take top 3
                    selected = options[:3]
                checklist_state[str(step)] = {
                    "question": question,
                    "selected": selected,
                }
                labels = [s.get("label", "?") for s in selected]
                print(f" -> {', '.join(labels[:4])}", file=sys.stderr)
        else:
            # Interactive mode
            print(f"\n{question}\n")

            if q_type == "free_text":
                answer = input("Your answer: ").strip()
                checklist_state[str(step)] = {
                    "question": question,
                    "answer": answer,
                }
            elif q_type in ("multiple_choice", "multiple_choice_with_custom", "preset_choice"):
                for i, opt in enumerate(options, 1):
                    pre = "[x]" if opt.get("pre_selected") else "[ ]"
                    label = opt.get("label", "?")
                    desc = opt.get("description", "")
                    reasoning = opt.get("ai_reasoning", "")
                    print(f"  {i}. {pre} {label}")
                    if desc:
                        print(f"       {desc}")
                    if reasoning:
                        print(f"       Reason: {reasoning}")

                print()
                if q_type == "preset_choice":
                    raw = input("Select one (number): ").strip()
                else:
                    raw = input(
                        "Select (comma-separated numbers, or 'a' to accept pre-selections): "
                    ).strip()

                if raw.lower() == "a":
                    selected = [o for o in options if o.get("pre_selected")]
                else:
                    indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip()]
                    selected = [options[i] for i in indices if 0 <= i < len(options)]

                if q_type == "multiple_choice_with_custom":
                    custom = input("Add custom (or Enter to skip): ").strip()
                    if custom:
                        selected.append({
                            "id": f"custom-{len(selected)}",
                            "type": "custom",
                            "label": custom,
                            "pre_selected": False,
                        })

                checklist_state[str(step)] = {
                    "question": question,
                    "selected": selected,
                }
                print(
                    f"\nSelected: {', '.join(s.get('label', '?') for s in selected)}",
                    file=sys.stderr,
                )
            else:
                answer = input("Your answer: ").strip()
                checklist_state[str(step)] = {
                    "question": question,
                    "answer": answer,
                }

    return {
        "name": topic_name,
        "checklist_state": checklist_state,
    }


def cmd_create_topic(args: argparse.Namespace) -> None:
    """Run the Topic Creator agent through the 8-step checklist."""
    if not GRAPH_PATH.exists():
        print("Error: no concept graph found. Run 'extract' first.", file=sys.stderr)
        sys.exit(1)

    g = graph.ConceptGraph.load(GRAPH_PATH)
    print(f"Loaded graph: {g.summary()}", file=sys.stderr)

    entities_path = Path(args.entities)
    if not entities_path.exists():
        print(f"Error: entities file not found: {entities_path}", file=sys.stderr)
        sys.exit(1)
    entities = json.loads(entities_path.read_text())

    auto = getattr(args, "auto", False)
    topic_data = _run_topic_checklist(
        args.name, f"Topic covering {args.name}.", g, entities, args, auto=auto,
    )
    if not topic_data:
        print("Error: topic creation failed.", file=sys.stderr)
        sys.exit(1)

    # Save
    slug = args.name.lower().replace(" ", "_").replace("&", "and")
    topic_path = TOPICS_DIR / f"{slug}.json"
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    topic_path.write_text(json.dumps(topic_data, indent=2))
    print(f"\nTopic saved to {topic_path}", file=sys.stderr)


def cmd_generate_topics(args: argparse.Namespace) -> None:
    """Auto-discover topic candidates from the concept graph and generate them.

    Clusters concepts by their inter-concept edges, then runs the Topic
    Creator agent in auto-accept mode for each cluster.
    """
    graph_path = Path(args.graph) if args.graph else GRAPH_PATH
    if not graph_path.exists():
        print("Error: no concept graph found. Run 'extract' first.", file=sys.stderr)
        sys.exit(1)

    g = graph.ConceptGraph.load(graph_path)
    print(f"Loaded graph: {g.summary()}", file=sys.stderr)

    entities_path = Path(args.entities)
    if not entities_path.exists():
        print(f"Error: entities file not found: {entities_path}", file=sys.stderr)
        sys.exit(1)
    entities = json.loads(entities_path.read_text())

    # Cluster concepts into topic candidates
    graph_dict = g.to_dict()
    candidates = clustering.cluster_concepts_into_topics(
        graph_dict,
        min_cluster_size=args.min_concepts,
        max_cluster_size=args.max_concepts,
    )

    # Filter to clusters with enough concepts
    viable = [c for c in candidates if len(c.concept_ids) >= args.min_concepts]

    print(f"\n{len(candidates)} clusters found, {len(viable)} viable topics "
          f"(>= {args.min_concepts} concepts):\n", file=sys.stderr)
    for i, tc in enumerate(viable):
        print(f"  {i+1}. {tc.name} ({len(tc.concept_ids)} concepts, "
              f"{tc.internal_edges} edges)", file=sys.stderr)
        for cn in tc.concept_names:
            print(f"       - {cn}", file=sys.stderr)
        print(file=sys.stderr)

    if args.dry_run:
        print("Dry run - not creating topics.", file=sys.stderr)
        return

    # Generate each topic
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    start = args.start_topic or 0

    for i, tc in enumerate(viable):
        if i < start:
            print(f"\nSkipping topic {i+1}: {tc.name}", file=sys.stderr)
            continue

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Topic {i+1}/{len(viable)}: {tc.name}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        topic_data = _run_topic_checklist(
            tc.name, tc.description, g, entities, args, auto=True,
        )

        if topic_data:
            topic_data["concept_cluster"] = {
                "concept_ids": tc.concept_ids,
                "concept_names": tc.concept_names,
                "internal_edges": tc.internal_edges,
            }

            slug = tc.name.lower().replace(" ", "_").replace("&", "and")
            slug = slug.replace("(", "").replace(")", "").replace("/", "_")
            slug = "_".join(slug.split())[:60]
            topic_path = TOPICS_DIR / f"{slug}.json"
            topic_path.write_text(json.dumps(topic_data, indent=2))
            results.append({"name": tc.name, "path": str(topic_path), "ok": True})
            print(f"  Saved: {topic_path}", file=sys.stderr)
        else:
            results.append({"name": tc.name, "path": "", "ok": False})
            print(f"  FAILED", file=sys.stderr)

    # Summary
    ok = sum(1 for r in results if r["ok"])
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Generated {ok}/{len(viable)} topics", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        print(f"  [{status}] {r['name']}", file=sys.stderr)


def _classify_datasets(datasets: list[dict]) -> dict[str, list[dict]]:
    """Classify datasets into domain buckets by keyword matching on names."""
    domain_keywords = {
        "marketing": ["marketing", "campaign", "mql", "sdr", "funnel", "lead", "prism"],
        "sales": ["salesforce", "sfdc", "opportunity", "pipeline", "deal", "quota", "booking"],
        "customer": ["customer", "account", "netsuite", "renewal", "churn", "retention", "cust_"],
        "product": ["product", "usage", "feature", "session", "event", "engagement", "dashboard", "segment"],
        "experimentation": ["experiment", "variant", "a/b", "flag", "feature flag", "variation"],
        "finance": ["revenue", "arr", "mrr", "billing", "invoice", "payment", "finance", "netsuite"],
        "data_infra": ["dwh_", "raw_", "stg_", "dim_", "fact_", "warehouse", "etl"],
    }
    buckets: dict[str, list[dict]] = {d: [] for d in domain_keywords}
    buckets["other"] = []

    for ds in datasets:
        name_lower = ds.get("name", "").lower()
        placed = False
        for domain, keywords in domain_keywords.items():
            if any(kw in name_lower for kw in keywords):
                buckets[domain].append(ds)
                placed = True
                break  # first match wins
        if not placed:
            buckets["other"].append(ds)

    # Remove empty buckets
    return {k: v for k, v in buckets.items() if v}


def _prepare_batch(datasets: list[dict], max_datasets: int = 15, max_cols: int = 8) -> list[dict]:
    """Prepare a batch of datasets with shortened names and limited columns."""
    batch = []
    for ds in datasets[:max_datasets]:
        name = ds.get("name", "")
        short_name = name.rsplit(".", 1)[-1] if "." in name else name
        cols = ds.get("columns", [])
        short_cols = [c.rsplit(".", 1)[-1] if "." in c else c for c in cols[:max_cols]]
        batch.append({"id": ds["id"], "name": short_name, "columns": short_cols})
    return batch


def cmd_batch_extract(args: argparse.Namespace) -> None:
    """Run the Concept Extractor incrementally across domain batches."""
    entities_path = Path(args.entities)
    if not entities_path.exists():
        print(f"Error: entities file not found: {entities_path}", file=sys.stderr)
        sys.exit(1)

    entities = json.loads(entities_path.read_text())
    all_datasets = entities.get("datasets", [])
    all_metrics = entities.get("metrics", [])
    all_events = entities.get("events", [])
    print(
        f"Loaded {len(all_datasets)} datasets, {len(all_metrics)} metrics, "
        f"{len(all_events)} events from {entities_path}",
        file=sys.stderr,
    )

    # Classify datasets into domain buckets
    buckets = _classify_datasets(all_datasets)
    domain_order = list(buckets.keys())
    print(f"\nDomain buckets:", file=sys.stderr)
    for domain, ds_list in buckets.items():
        print(f"  {domain}: {len(ds_list)} datasets", file=sys.stderr)

    # First batch includes metrics and events. Subsequent batches are datasets only.
    if GRAPH_PATH.exists() and not args.reset:
        existing = graph.ConceptGraph.load(GRAPH_PATH)
        print(f"\nResuming from existing graph: {existing.summary()}", file=sys.stderr)
    else:
        existing = graph.ConceptGraph()
        if GRAPH_PATH.exists() and args.reset:
            GRAPH_PATH.unlink()
            print("Reset: cleared existing graph", file=sys.stderr)

    # Flatten domains into sub-batches of max 15 datasets each
    max_per_batch = 15
    flat_batches: list[tuple[str, list[dict]]] = []
    for domain in domain_order:
        ds_list = buckets[domain]
        for i in range(0, len(ds_list), max_per_batch):
            chunk = ds_list[i:i + max_per_batch]
            suffix = f"-{i // max_per_batch + 1}" if len(ds_list) > max_per_batch else ""
            flat_batches.append((f"{domain}{suffix}", chunk))

    total_batches = len(flat_batches)
    print(f"\n{total_batches} batches planned across {len(domain_order)} domains", file=sys.stderr)

    start_batch = args.start_batch if args.start_batch else 0
    batch_results: list[dict] = []

    for batch_idx, (batch_name, ds_list) in enumerate(flat_batches):
        if batch_idx < start_batch:
            print(f"\nSkipping batch {batch_idx} ({batch_name})", file=sys.stderr)
            continue

        batch_datasets = _prepare_batch(ds_list, max_datasets=max_per_batch, max_cols=8)

        batch_entity = {
            "app_id": entities.get("app_id", args.app_id),
            "batch": f"{batch_name} ({batch_idx + 1}/{total_batches})",
            "datasets": batch_datasets,
        }
        # Include metrics and events only in the first batch
        if batch_idx == start_batch:
            batch_entity["metrics"] = [
                {"id": m["id"], "name": m["name"]}
                for m in all_metrics[:20]
            ]
            batch_entity["events"] = [
                {"id": e["id"], "name": e["name"]}
                for e in all_events
            ]

        metadata_str = json.dumps(batch_entity)
        print(
            f"\n{'='*60}\n"
            f"Batch {batch_idx + 1}/{total_batches}: {batch_name} "
            f"({len(batch_datasets)} datasets, {len(metadata_str):,} chars)\n"
            f"{'='*60}",
            file=sys.stderr,
        )

        parameters = {
            "app_id": args.app_id,
            "metadata_image": metadata_str,
            "focus": "all",
        }
        if args.hints:
            parameters["admin_hints"] = args.hints

        # Pass existing concepts
        concepts = existing.get_concepts()
        if concepts:
            parameters["existing_concepts"] = json.dumps(
                [{"name": c.name, "description": c.description} for c in concepts]
            )
            print(
                f"Passing {len(concepts)} existing concepts to the agent",
                file=sys.stderr,
            )

        try:
            result = client.execute_agent(
                args.agent_id,
                parameters,
                args.env,
                args.instance,
            )
        except Exception as e:
            print(f"\nError in batch {batch_idx} ({batch_name}): {e}", file=sys.stderr)
            print("Saving progress and stopping.", file=sys.stderr)
            existing.save(GRAPH_PATH)
            print(
                f"Graph saved. Resume with --start-batch {batch_idx}",
                file=sys.stderr,
            )
            sys.exit(1)

        output = result.get("output")
        if not output:
            print(
                f"Warning: no parseable output for batch {batch_idx} ({batch_name}). "
                f"Raw: {result.get('raw_text', '')[:500]}",
                file=sys.stderr,
            )
            continue

        # Merge into graph
        existing.add_from_extraction(output)
        existing.save(GRAPH_PATH)

        summary = output.get("summary", {})
        new_concepts = summary.get("total_concepts_proposed", 0)
        batch_results.append({"domain": batch_name, "concepts": new_concepts, "summary": summary})
        print(
            f"\nBatch {batch_idx + 1} done: +{new_concepts} concepts. "
            f"Graph now: {existing.summary()}",
            file=sys.stderr,
        )

    # Final summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Batch extraction complete", file=sys.stderr)
    print(f"Final graph: {existing.summary()}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    for br in batch_results:
        print(f"  {br['domain']}: +{br['concepts']} concepts", file=sys.stderr)


def _run_extraction_batch(
    batch_label: str,
    batch_entity: dict,
    existing: graph.ConceptGraph,
    args: argparse.Namespace,
) -> dict | None:
    """Run a single extraction batch and merge results. Returns output or None."""
    metadata_str = json.dumps(batch_entity)
    print(
        f"\n{'='*60}\n"
        f"{batch_label} ({len(batch_entity.get('datasets', []))} datasets, "
        f"{len(metadata_str):,} chars)\n"
        f"{'='*60}",
        file=sys.stderr,
    )

    parameters = {
        "app_id": args.app_id,
        "metadata_image": metadata_str,
        "focus": "all",
    }
    if args.hints:
        parameters["admin_hints"] = args.hints

    concepts = existing.get_concepts()
    if concepts:
        parameters["existing_concepts"] = json.dumps(
            [{"name": c.name, "description": c.description} for c in concepts]
        )
        print(f"Passing {len(concepts)} existing concepts", file=sys.stderr)

    result = client.execute_agent(
        args.agent_id,
        parameters,
        args.env,
        args.instance,
    )

    output = result.get("output")
    if not output:
        print(
            f"Warning: no parseable output. Raw: {result.get('raw_text', '')[:500]}",
            file=sys.stderr,
        )
        return None

    existing.add_from_extraction(output)
    existing.save(GRAPH_PATH)
    summary = output.get("summary", {})
    print(
        f"\nDone: +{summary.get('total_concepts_proposed', '?')} concepts. "
        f"Graph: {existing.summary()}",
        file=sys.stderr,
    )
    return output


def cmd_stratified_extract(args: argparse.Namespace) -> None:
    """Run concept extraction using relationship-based stratified batching.

    Three layers:
        Layer 1 (core): Hub datasets clustered by shared join keys.
            Discovers foundational cross-domain concepts.
        Layer 2 (domain): Connected datasets grouped by co-occurrence.
            Enriches existing concepts, discovers domain-specific ones.
        Layer 3 (isolated): Datasets with no shared columns.
            Catches remaining signals.

    After all layers: optional consolidation pass reviewing all concepts.
    """
    entities_path = Path(args.entities)
    if not entities_path.exists():
        print(f"Error: entities file not found: {entities_path}", file=sys.stderr)
        sys.exit(1)

    entities = json.loads(entities_path.read_text())
    all_datasets = entities.get("datasets", [])
    all_metrics = entities.get("metrics", [])
    all_events = entities.get("events", [])
    print(
        f"Loaded {len(all_datasets)} datasets, {len(all_metrics)} metrics, "
        f"{len(all_events)} events",
        file=sys.stderr,
    )

    # Build the stratified batch plan
    plan = clustering.build_batch_plan(all_datasets, max_per_batch=15)
    print(f"\nBatch plan:\n{plan.summary()}", file=sys.stderr)

    if plan.join_key_stats:
        print("\nTop join keys:", file=sys.stderr)
        for col, count in list(plan.join_key_stats.items())[:10]:
            print(f"  {col}: {count} datasets", file=sys.stderr)

    # Print batch details
    for i, batch in enumerate(plan.batches):
        ds_preview = [plan.ds_names.get(d, "?")[:40] for d in batch.dataset_ids[:4]]
        overflow = f" +{len(batch.dataset_ids) - 4}" if len(batch.dataset_ids) > 4 else ""
        print(
            f"  [{i:2}] L{batch.layer} {batch.name:15} "
            f"{len(batch.dataset_ids):2}ds coh={batch.cohesion:.1f}  "
            f"{ds_preview}{overflow}",
            file=sys.stderr,
        )

    # Initialise or resume graph
    if GRAPH_PATH.exists() and not args.reset:
        existing = graph.ConceptGraph.load(GRAPH_PATH)
        print(f"\nResuming from existing graph: {existing.summary()}", file=sys.stderr)
    else:
        existing = graph.ConceptGraph()
        if GRAPH_PATH.exists() and args.reset:
            GRAPH_PATH.unlink()
            print("Reset: cleared existing graph", file=sys.stderr)

    start_batch = args.start_batch or 0
    batch_results: list[dict] = []
    total = len(plan.batches)

    for batch_idx, batch in enumerate(plan.batches):
        if batch_idx < start_batch:
            print(f"\nSkipping batch {batch_idx} ({batch.name})", file=sys.stderr)
            continue

        # Resolve dataset dicts from IDs
        ds_lookup = {ds["id"]: ds for ds in all_datasets}
        batch_ds = [ds_lookup[did] for did in batch.dataset_ids if did in ds_lookup]

        # Prepare compact representation
        prepared = _prepare_batch(batch_ds, max_datasets=15, max_cols=10)

        batch_entity: dict[str, Any] = {
            "app_id": entities.get("app_id", args.app_id),
            "batch": f"{batch.name} (L{batch.layer}, {batch_idx + 1}/{total})",
            "datasets": prepared,
        }

        # Include metrics and events in the first batch of each layer
        layer_first = not any(
            br.get("layer") == batch.layer for br in batch_results
        )
        if layer_first:
            batch_entity["metrics"] = [
                {"id": m["id"], "name": m["name"]}
                for m in all_metrics[:20]
            ]
            batch_entity["events"] = [
                {"id": e["id"], "name": e["name"]}
                for e in all_events
            ]

        label = f"Batch {batch_idx + 1}/{total}: {batch.name} (L{batch.layer})"

        try:
            output = _run_extraction_batch(label, batch_entity, existing, args)
        except Exception as e:
            print(f"\nError in batch {batch_idx} ({batch.name}): {e}", file=sys.stderr)
            existing.save(GRAPH_PATH)
            print(f"Graph saved. Resume with --start-batch {batch_idx}", file=sys.stderr)
            sys.exit(1)

        if output:
            summary = output.get("summary", {})
            batch_results.append({
                "batch": batch.name,
                "layer": batch.layer,
                "concepts": summary.get("total_concepts_proposed", 0),
            })

    # Final summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Stratified extraction complete", file=sys.stderr)
    print(f"Final graph: {existing.summary()}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    for layer in (1, 2, 3):
        layer_results = [br for br in batch_results if br["layer"] == layer]
        if layer_results:
            total_concepts = sum(br["concepts"] for br in layer_results)
            label = {1: "Core", 2: "Domain", 3: "Isolated"}.get(layer, f"L{layer}")
            print(f"\n  Layer {layer} ({label}): +{total_concepts} concepts", file=sys.stderr)
            for br in layer_results:
                print(f"    {br['batch']}: +{br['concepts']}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="M2 concept/topic generation test harness",
    )
    parser.add_argument("--env", default="prod", help="Opal environment (default: prod)")
    parser.add_argument("--instance", help="Opal instance ID")
    sub = parser.add_subparsers(dest="command", required=True)

    # list-agents
    sub.add_parser("list-agents", help="List specialized agents on the instance")

    # extract
    p_extract = sub.add_parser("extract", help="Run the Concept Extractor agent")
    p_extract.add_argument("--agent-id", required=True, help="Agent UUID or slug")
    p_extract.add_argument("--app-id", required=True, help="OA app UUID")
    p_extract.add_argument("--entities", required=True, help="Path to entities JSON file")
    p_extract.add_argument("--focus", default="all", help="Focus: all, datasets, columns, events, metrics")
    p_extract.add_argument("--hints", help="Admin hints for the extractor")

    # batch-extract
    p_batch = sub.add_parser("batch-extract", help="Run Concept Extractor incrementally across domain batches")
    p_batch.add_argument("--agent-id", required=True, help="Agent UUID or slug")
    p_batch.add_argument("--app-id", required=True, help="OA app UUID")
    p_batch.add_argument("--entities", required=True, help="Path to full entities JSON file")
    p_batch.add_argument("--hints", help="Admin hints for the extractor")
    p_batch.add_argument("--start-batch", type=int, default=0, help="Resume from batch N (0-indexed)")
    p_batch.add_argument("--reset", action="store_true", help="Clear existing graph before starting")

    # stratified-extract
    p_strat = sub.add_parser(
        "stratified-extract",
        help="Run Concept Extractor with relationship-based stratified batching",
    )
    p_strat.add_argument("--agent-id", required=True, help="Agent UUID or slug")
    p_strat.add_argument("--app-id", required=True, help="OA app UUID")
    p_strat.add_argument("--entities", required=True, help="Path to full entities JSON file")
    p_strat.add_argument("--hints", help="Admin hints for the extractor")
    p_strat.add_argument("--start-batch", type=int, default=0, help="Resume from batch N (0-indexed)")
    p_strat.add_argument("--reset", action="store_true", help="Clear existing graph before starting")

    # create-topic
    p_topic = sub.add_parser("create-topic", help="Run the Topic Creator through the 8-step checklist")
    p_topic.add_argument("--agent-id", required=True, help="Agent UUID or slug")
    p_topic.add_argument("--name", required=True, help="Topic name")
    p_topic.add_argument("--app-id", help="OA app UUID (optional)")
    p_topic.add_argument("--entities", required=True, help="Path to entities JSON file")
    p_topic.add_argument("--auto", action="store_true", help="Auto-accept agent pre-selections")

    # generate-topics
    p_gen = sub.add_parser(
        "generate-topics",
        help="Auto-discover and generate topics from the concept graph",
    )
    p_gen.add_argument("--agent-id", required=True, help="Topic Creator agent UUID or slug")
    p_gen.add_argument("--app-id", help="OA app UUID (optional)")
    p_gen.add_argument("--entities", required=True, help="Path to entities JSON file")
    p_gen.add_argument("--graph", help="Path to concept graph JSON (default: output/concept_graph.json)")
    p_gen.add_argument("--min-concepts", type=int, default=2, help="Minimum concepts per topic (default: 2)")
    p_gen.add_argument("--max-concepts", type=int, default=10, help="Maximum concepts per topic (default: 10)")
    p_gen.add_argument("--start-topic", type=int, default=0, help="Resume from topic N (0-indexed)")
    p_gen.add_argument("--dry-run", action="store_true", help="Show topic candidates without generating")

    args = parser.parse_args()

    if args.command == "list-agents":
        cmd_list_agents(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "batch-extract":
        cmd_batch_extract(args)
    elif args.command == "stratified-extract":
        cmd_stratified_extract(args)
    elif args.command == "create-topic":
        cmd_create_topic(args)
    elif args.command == "generate-topics":
        cmd_generate_topics(args)


if __name__ == "__main__":
    main()
