"""Entity description generation - batching, review loop, and merging.

Coordinates calls to the oa-entity-describer agent, handles batching
by entity type and domain, manages multi-round context accumulation,
and merges confirmed descriptions back into the entities file.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DescriptionCandidate:
    entity_id: str
    entity_type: str
    entity_name: str
    parent_dataset: str | None
    description: str
    confidence: str  # high, medium, low
    action: str  # generate, improve, replace, keep
    needs_review: bool
    review_reason: str | None = None


@dataclass
class FollowUpQuestion:
    question_id: str
    entity_ids: list[str]
    question: str
    context: str
    options: list[dict[str, str]]


@dataclass
class DescriptionRound:
    """Results from one round of entity description."""
    candidates: list[DescriptionCandidate] = field(default_factory=list)
    follow_ups: list[FollowUpQuestion] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


def group_datasets_by_domain(datasets: list[dict]) -> dict[str, list[dict]]:
    """Group datasets by folder path prefix for domain-coherent batching."""
    groups: dict[str, list[dict]] = {}
    for ds in datasets:
        name = ds.get("name", "")
        # Use top-level folder as domain key
        # e.g. "Analytics & Data.Insight & Analysis.02 Sales.FOO" -> "Analytics & Data"
        parts = name.split(".")
        if len(parts) >= 2:
            domain = parts[0]
        else:
            # No folder structure - classify by keyword
            lower = name.lower()
            if any(k in lower for k in ("sales", "opp", "pipe", "booking", "quota")):
                domain = "Sales"
            elif any(k in lower for k in ("customer", "cs_", "renewal", "churn", "account")):
                domain = "Customer"
            elif any(k in lower for k in ("product", "usage", "feature", "segment", "event")):
                domain = "Product"
            elif any(k in lower for k in ("marketing", "campaign", "mql", "lead")):
                domain = "Marketing"
            elif any(k in lower for k in ("experiment", "variant", "exp_")):
                domain = "Experimentation"
            elif any(k in lower for k in ("dwh_", "raw_", "stg_", "dim_", "fact_")):
                domain = "Data Infrastructure"
            else:
                domain = "Other"
        groups.setdefault(domain, []).append(ds)
    return groups


def build_dataset_batches(
    datasets: list[dict],
    max_per_batch: int = 15,
    max_cols_per_ds: int = 50,
) -> list[tuple[str, list[dict]]]:
    """Build domain-grouped batches of datasets with their columns.

    Returns list of (batch_label, datasets_with_columns) tuples.
    Columns are trimmed to max_cols_per_ds to control payload size.
    """
    groups = group_datasets_by_domain(datasets)
    batches: list[tuple[str, list[dict]]] = []

    for domain, ds_list in sorted(groups.items()):
        for i in range(0, len(ds_list), max_per_batch):
            chunk = ds_list[i:i + max_per_batch]
            suffix = f" ({i // max_per_batch + 1})" if len(ds_list) > max_per_batch else ""
            label = f"{domain}{suffix}"

            # Trim columns per dataset
            trimmed = []
            for ds in chunk:
                ds_copy = {
                    "id": ds["id"],
                    "name": ds["name"],
                    "description": ds.get("description") or "",
                }
                cols = ds.get("columns", [])
                if cols:
                    trimmed_cols = []
                    for c in cols[:max_cols_per_ds]:
                        if isinstance(c, dict):
                            trimmed_cols.append({
                                "id": c.get("id", ""),
                                "name": c.get("name", ""),
                                "description": c.get("description") or "",
                            })
                        else:
                            trimmed_cols.append({"name": str(c), "description": ""})
                    ds_copy["columns"] = trimmed_cols
                    if len(cols) > max_cols_per_ds:
                        ds_copy["columns_truncated"] = len(cols) - max_cols_per_ds
                trimmed.append(ds_copy)

            batches.append((label, trimmed))

    return batches


def build_metric_batches(
    metrics: list[dict],
    max_per_batch: int = 50,
) -> list[tuple[str, list[dict]]]:
    """Build batches of metrics."""
    batches: list[tuple[str, list[dict]]] = []
    for i in range(0, len(metrics), max_per_batch):
        chunk = metrics[i:i + max_per_batch]
        label = f"Metrics ({i // max_per_batch + 1})" if len(metrics) > max_per_batch else "Metrics"
        items = [
            {
                "id": m["id"],
                "name": m["name"],
                "description": m.get("description") or "",
            }
            for m in chunk
        ]
        batches.append((label, items))
    return batches


def build_event_batch(events: list[dict]) -> tuple[str, list[dict]]:
    """Build a single batch of all events."""
    items = [
        {
            "id": e["id"],
            "name": e["name"],
            "description": e.get("description") or "",
        }
        for e in events
    ]
    return ("Events", items)


def parse_description_output(output: dict) -> DescriptionRound:
    """Parse the agent's JSON output into a DescriptionRound."""
    result = DescriptionRound()

    for d in output.get("descriptions", []):
        result.candidates.append(DescriptionCandidate(
            entity_id=d.get("entity_id", ""),
            entity_type=d.get("entity_type", ""),
            entity_name=d.get("entity_name", ""),
            parent_dataset=d.get("parent_dataset"),
            description=d.get("description", ""),
            confidence=d.get("confidence", "medium"),
            action=d.get("action", "generate"),
            needs_review=d.get("needs_review", False),
            review_reason=d.get("review_reason"),
        ))

    for fq in output.get("follow_up_questions", []):
        result.follow_ups.append(FollowUpQuestion(
            question_id=fq.get("question_id", ""),
            entity_ids=fq.get("entity_ids", []),
            question=fq.get("question", ""),
            context=fq.get("context", ""),
            options=fq.get("options", []),
        ))

    result.summary = output.get("summary", {})
    return result


def present_review(
    round_result: DescriptionRound,
    auto: bool = False,
) -> list[DescriptionCandidate]:
    """Present descriptions for human review.

    In auto mode, accepts high+medium confidence, flags low for review.
    Returns the list of confirmed (accepted) candidates.
    """
    confirmed: list[DescriptionCandidate] = []

    by_confidence = {"high": [], "medium": [], "low": []}
    for c in round_result.candidates:
        if c.action == "keep":
            confirmed.append(c)
            continue
        by_confidence.setdefault(c.confidence, []).append(c)

    # High confidence: auto-accept
    high = by_confidence.get("high", [])
    if high:
        print(f"\n  High confidence ({len(high)} descriptions) - auto-accepted", file=sys.stderr)
        confirmed.extend(high)

    # Medium confidence: accept in auto mode, show for scan in interactive
    medium = by_confidence.get("medium", [])
    if medium:
        if auto:
            print(f"  Medium confidence ({len(medium)} descriptions) - auto-accepted", file=sys.stderr)
            confirmed.extend(medium)
        else:
            print(f"\n  Medium confidence ({len(medium)} descriptions) - review:", file=sys.stderr)
            for c in medium:
                action_tag = f" [{c.action}]" if c.action != "generate" else ""
                print(f"    {c.entity_type:8} {c.entity_name}", file=sys.stderr)
                print(f"             {c.description[:120]}...{action_tag}", file=sys.stderr)

            raw = input("\n  Accept all medium? (y/n/list numbers to reject): ").strip()
            if raw.lower() in ("y", "yes", ""):
                confirmed.extend(medium)
            elif raw.lower() in ("n", "no"):
                pass  # reject all medium
            else:
                # Reject specific indices
                reject = set()
                for part in raw.split(","):
                    try:
                        reject.add(int(part.strip()) - 1)
                    except ValueError:
                        pass
                for i, c in enumerate(medium):
                    if i not in reject:
                        confirmed.append(c)

    # Low confidence: show for detailed review
    low = by_confidence.get("low", [])
    if low:
        if auto:
            print(f"  Low confidence ({len(low)} descriptions) - auto-accepted with flag", file=sys.stderr)
            confirmed.extend(low)
        else:
            print(f"\n  Low confidence ({len(low)} descriptions) - detailed review:", file=sys.stderr)
            for i, c in enumerate(low):
                print(f"\n    {i+1}. [{c.entity_type}] {c.entity_name}", file=sys.stderr)
                print(f"       {c.description}", file=sys.stderr)
                if c.review_reason:
                    print(f"       Reason: {c.review_reason}", file=sys.stderr)

                raw = input("       Accept? (y/n/edit): ").strip()
                if raw.lower() in ("y", "yes", ""):
                    confirmed.append(c)
                elif raw.lower().startswith("e"):
                    edited = input("       New description: ").strip()
                    if edited:
                        c.description = edited
                        c.confidence = "human-edited"
                    confirmed.append(c)
                # else: rejected

    # Follow-up questions (interactive only)
    if round_result.follow_ups and not auto:
        print(f"\n  Follow-up questions ({len(round_result.follow_ups)}):", file=sys.stderr)
        answers = []
        for fq in round_result.follow_ups:
            print(f"\n    {fq.question}", file=sys.stderr)
            if fq.context:
                print(f"    Context: {fq.context}", file=sys.stderr)
            for opt in fq.options:
                print(f"      {opt.get('label', '?')}. {opt.get('text', '')}", file=sys.stderr)
            raw = input("    Your answer (letter or free text): ").strip()
            answers.append({"question_id": fq.question_id, "answer": raw})
        # Store answers for next round
        round_result.follow_up_answers = answers

    return confirmed


def merge_descriptions_into_entities(
    entities: dict,
    confirmed: list[DescriptionCandidate],
) -> dict:
    """Merge confirmed descriptions into the entities structure.

    Returns a new entities dict with descriptions applied.
    """
    # Build lookup for fast access
    ds_by_id = {ds["id"]: ds for ds in entities.get("datasets", [])}
    m_by_id = {m["id"]: m for m in entities.get("metrics", [])}
    e_by_id = {e["id"]: e for e in entities.get("events", [])}

    applied = 0
    for c in confirmed:
        if c.entity_type == "dataset":
            if c.entity_id in ds_by_id:
                ds_by_id[c.entity_id]["description"] = c.description
                applied += 1
        elif c.entity_type == "column":
            # Find the column in its parent dataset
            for ds in entities.get("datasets", []):
                for col in ds.get("columns", []):
                    if isinstance(col, dict) and col.get("id") == c.entity_id:
                        col["description"] = c.description
                        applied += 1
                        break
        elif c.entity_type == "metric":
            if c.entity_id in m_by_id:
                m_by_id[c.entity_id]["description"] = c.description
                applied += 1
        elif c.entity_type == "event":
            if c.entity_id in e_by_id:
                e_by_id[c.entity_id]["description"] = c.description
                applied += 1

    print(f"\n  Applied {applied}/{len(confirmed)} descriptions", file=sys.stderr)
    return entities


def save_round_output(
    round_num: int,
    batch_label: str,
    output: dict,
    output_dir: Path,
) -> None:
    """Save raw agent output for a batch."""
    desc_dir = output_dir / "descriptions"
    desc_dir.mkdir(parents=True, exist_ok=True)
    slug = batch_label.lower().replace(" ", "_").replace("(", "").replace(")", "")
    path = desc_dir / f"round_{round_num}_{slug}.json"
    path.write_text(json.dumps(output, indent=2))
    print(f"  Saved: {path}", file=sys.stderr)


def save_confirmed(
    confirmed: list[DescriptionCandidate],
    output_dir: Path,
) -> None:
    """Save the merged confirmed descriptions."""
    desc_dir = output_dir / "descriptions"
    desc_dir.mkdir(parents=True, exist_ok=True)
    path = desc_dir / "confirmed_descriptions.json"

    # Load existing if present
    existing: list[dict] = []
    if path.exists():
        existing = json.loads(path.read_text())

    existing_ids = {d["entity_id"] for d in existing}
    new_entries = []
    updated = 0
    for c in confirmed:
        entry = {
            "entity_id": c.entity_id,
            "entity_type": c.entity_type,
            "entity_name": c.entity_name,
            "parent_dataset": c.parent_dataset,
            "description": c.description,
            "confidence": c.confidence,
            "action": c.action,
        }
        if c.entity_id in existing_ids:
            # Update existing entry
            for i, e in enumerate(existing):
                if e["entity_id"] == c.entity_id:
                    existing[i] = entry
                    updated += 1
                    break
        else:
            new_entries.append(entry)

    existing.extend(new_entries)
    path.write_text(json.dumps(existing, indent=2))
    print(
        f"  Confirmed: {len(new_entries)} new, {updated} updated, "
        f"{len(existing)} total",
        file=sys.stderr,
    )


def generate_review_report(
    all_candidates: list[DescriptionCandidate],
    all_follow_ups: list[FollowUpQuestion],
    output_dir: Path,
) -> None:
    """Write a human-readable review report."""
    desc_dir = output_dir / "descriptions"
    desc_dir.mkdir(parents=True, exist_ok=True)
    path = desc_dir / "review_report.md"

    lines = ["# Entity Description Review Report\n"]

    # Summary
    by_confidence = {"high": 0, "medium": 0, "low": 0}
    by_action = {"generate": 0, "improve": 0, "replace": 0, "keep": 0}
    by_type = {}
    for c in all_candidates:
        by_confidence[c.confidence] = by_confidence.get(c.confidence, 0) + 1
        by_action[c.action] = by_action.get(c.action, 0) + 1
        by_type[c.entity_type] = by_type.get(c.entity_type, 0) + 1

    lines.append(f"**Total descriptions:** {len(all_candidates)}\n")
    lines.append("| Confidence | Count |")
    lines.append("|------------|-------|")
    for conf, count in by_confidence.items():
        lines.append(f"| {conf} | {count} |")
    lines.append("")

    lines.append("| Action | Count |")
    lines.append("|--------|-------|")
    for action, count in by_action.items():
        lines.append(f"| {action} | {count} |")
    lines.append("")

    lines.append("| Entity type | Count |")
    lines.append("|-------------|-------|")
    for etype, count in sorted(by_type.items()):
        lines.append(f"| {etype} | {count} |")
    lines.append("")

    # Needs review
    needs_review = [c for c in all_candidates if c.needs_review]
    if needs_review:
        lines.append(f"## Needs Review ({len(needs_review)})\n")
        for c in needs_review:
            lines.append(f"### {c.entity_name}")
            lines.append(f"**Type:** {c.entity_type} | **Confidence:** {c.confidence} | **Action:** {c.action}")
            if c.review_reason:
                lines.append(f"**Reason:** {c.review_reason}")
            lines.append(f"> {c.description}\n")

    # Follow-up questions
    if all_follow_ups:
        lines.append(f"## Follow-up Questions ({len(all_follow_ups)})\n")
        for fq in all_follow_ups:
            lines.append(f"### {fq.question}")
            lines.append(f"**Context:** {fq.context}")
            lines.append(f"**Affects:** {', '.join(fq.entity_ids)}")
            for opt in fq.options:
                lines.append(f"- **{opt.get('label', '?')}:** {opt.get('text', '')}")
            lines.append("")

    path.write_text("\n".join(lines))
    print(f"  Report: {path}", file=sys.stderr)
