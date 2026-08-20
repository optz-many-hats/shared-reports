#!/usr/bin/env python3
"""
Build combined data payloads for entity-graph.html visualisation.

Reads the full graph data and all topic JSON files, then:
  1. Builds a TOPICS dict keyed by slug (filename without .json).
  2. Annotates each graph node with a `topics` array listing which
     topic slugs include that node ID as a member.
  3. Writes two output files:
     - graph_with_topics.json  (nodes + edges, nodes have `topics` arrays)
     - topics_data.json        (TOPICS dict keyed by slug)

Member IDs are gathered from each topic file as follows:
  - concept_cluster.concept_ids
  - checklist_state steps 2-5: each selected item's `id`
  (Steps 6-7 contain business rules/disambiguations with synthetic IDs
   that do not correspond to graph nodes, so they are excluded.)
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent / "output"
GRAPH_PATH = BASE / "full_graph_data.json"
ENTITIES_PATH = BASE / "enriched_entities.json"
TOPICS_DIR = BASE / "topics"
OUT_GRAPH = BASE / "graph_with_topics.json"
OUT_TOPICS = BASE / "topics_data.json"

# Entity-bearing checklist steps (steps 6-7 are rules, not graph entities)
ENTITY_STEPS = ("2", "3", "4", "5")


def collect_member_ids(topic: dict) -> set[str]:
    """Extract all graph-entity IDs that belong to a topic."""
    ids: set[str] = set()

    # concept_cluster.concept_ids
    cc = topic.get("concept_cluster", {})
    ids.update(cc.get("concept_ids", []))

    # checklist_state steps 2-5
    cs = topic.get("checklist_state", {})
    for step in ENTITY_STEPS:
        for item in cs.get(step, {}).get("selected", []):
            ids.add(item["id"])

    return ids


def main() -> None:
    # --- Load graph ---
    with open(GRAPH_PATH) as f:
        graph = json.load(f)

    nodes = graph["nodes"]  # dict keyed by node ID
    edges = graph["edges"]  # list

    # --- Load topics ---
    topics: dict[str, dict] = {}
    topic_files = sorted(TOPICS_DIR.glob("*.json"))

    if not topic_files:
        print("ERROR: no topic files found in", TOPICS_DIR, file=sys.stderr)
        sys.exit(1)

    # slug -> set of member IDs (for reverse lookup)
    slug_to_members: dict[str, set[str]] = {}

    for tf in topic_files:
        slug = tf.stem
        with open(tf) as f:
            topic_data = json.load(f)
        topics[slug] = topic_data
        slug_to_members[slug] = collect_member_ids(topic_data)

    # --- Add structural entity-to-entity edges ---
    with open(ENTITIES_PATH) as f:
        entities = json.load(f)

    col_nodes = {nid for nid, n in nodes.items() if n.get("type") == "column"}
    ds_nodes = {nid for nid, n in nodes.items() if n.get("type") == "dataset"}

    # Build column short-name -> [dataset_id] lookup from enriched entities
    name_to_datasets: dict[str, list[str]] = {}
    for ds in entities.get("datasets", []):
        for col in ds.get("columns", []):
            short = col["name"].rsplit(".", 1)[-1]
            name_to_datasets.setdefault(short, []).append(ds["id"])

    # Use concept co-occurrence to disambiguate short column names
    col_concepts: dict[str, set[str]] = {}
    ds_concepts: dict[str, set[str]] = {}
    for e in edges:
        src_type = nodes.get(e["source"], {}).get("type")
        tgt_type = nodes.get(e["target"], {}).get("type")
        if src_type == "concept" and tgt_type == "column":
            col_concepts.setdefault(e["target"], set()).add(e["source"])
        if src_type == "concept" and tgt_type == "dataset":
            ds_concepts.setdefault(e["target"], set()).add(e["source"])

    structural_edges = 0
    for cid in col_nodes:
        ds_id = None
        # Prefixed column IDs: dataset_id::COL or dataset_id.COL
        if "::" in cid:
            ds_id = cid.split("::")[0]
        elif "." in cid:
            ds_id = cid.split(".")[0]

        if ds_id and ds_id in ds_nodes:
            edges.append({
                "source": cid, "target": ds_id,
                "predicate": "belongs-to",
                "reasoning": "Column is defined in this dataset.",
            })
            structural_edges += 1
            continue

        # Short-name column: resolve via enriched entities
        name = nodes[cid].get("name", "")
        candidates = [d for d in name_to_datasets.get(name, []) if d in ds_nodes]
        if len(candidates) == 1:
            ds_id = candidates[0]
        elif len(candidates) > 1:
            # Disambiguate by shared concepts
            cc = col_concepts.get(cid, set())
            best, best_n = None, 0
            for d in candidates:
                n = len(cc & ds_concepts.get(d, set()))
                if n > best_n:
                    best, best_n = d, n
            ds_id = best

        if ds_id:
            edges.append({
                "source": cid, "target": ds_id,
                "predicate": "belongs-to",
                "reasoning": "Column is defined in this dataset.",
            })
            structural_edges += 1

    print(f"Structural edges added:       {structural_edges}")

    # --- Annotate nodes with topic membership ---
    nodes_with_topics_count = 0
    total_members_across_topics = sum(len(m) for m in slug_to_members.values())

    for node_id, node in nodes.items():
        matching_slugs = [
            slug
            for slug, members in slug_to_members.items()
            if node_id in members
        ]
        node["topics"] = matching_slugs
        if matching_slugs:
            nodes_with_topics_count += 1

    # --- Write outputs ---
    with open(OUT_GRAPH, "w") as f:
        json.dump({"nodes": nodes, "edges": edges}, f, indent=2)

    with open(OUT_TOPICS, "w") as f:
        json.dump(topics, f, indent=2)

    # --- Stats ---
    print(f"Topics loaded:                {len(topics)}")
    print(f"Topic slugs:                  {', '.join(sorted(topics.keys()))}")
    print(f"Graph nodes:                  {len(nodes)}")
    print(f"Graph edges:                  {len(edges)}")
    print(f"Nodes with topic assignments: {nodes_with_topics_count}")
    print(f"Total members across topics:  {total_members_across_topics}")
    print()
    print(f"Wrote: {OUT_GRAPH}")
    print(f"Wrote: {OUT_TOPICS}")


if __name__ == "__main__":
    main()
