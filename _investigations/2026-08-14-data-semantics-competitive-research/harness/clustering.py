"""Entity relationship clustering for stratified concept extraction.

Builds a co-occurrence graph of datasets based on shared column names (join
keys), then clusters datasets into batches that maximise semantic cohesion.

Layers:
    Layer 1 (core): High-connectivity hub clusters - foundational concepts.
    Layer 2 (domain): Medium-connectivity clusters - domain enrichment.
    Layer 3 (isolated): Datasets with no shared columns.

Also provides concept-level clustering for automatic topic discovery.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Batch:
    name: str
    layer: int  # 1, 2, or 3
    dataset_ids: list[str]
    cohesion: float = 0.0


@dataclass
class BatchPlan:
    batches: list[Batch]
    ds_names: dict[str, str]  # id -> short name
    join_key_stats: dict[str, int] = field(default_factory=dict)  # col -> count

    @property
    def total_datasets(self) -> int:
        return sum(len(b.dataset_ids) for b in self.batches)

    def summary(self) -> str:
        by_layer = defaultdict(list)
        for b in self.batches:
            by_layer[b.layer].append(b)
        lines = [f"{len(self.batches)} batches, {self.total_datasets} datasets"]
        for layer in sorted(by_layer):
            layer_batches = by_layer[layer]
            n_ds = sum(len(b.dataset_ids) for b in layer_batches)
            label = {1: "core", 2: "domain", 3: "isolated"}.get(layer, f"L{layer}")
            lines.append(f"  Layer {layer} ({label}): {len(layer_batches)} batches, {n_ds} datasets")
        return "\n".join(lines)


def build_batch_plan(
    datasets: list[dict[str, Any]],
    max_per_batch: int = 15,
    hub_threshold: int = 200,
) -> BatchPlan:
    """Build a stratified batch plan from dataset metadata.

    Args:
        datasets: List of dataset dicts with 'id', 'name', 'columns' keys.
            Column values can be full dotted paths - the last segment is used.
        max_per_batch: Maximum datasets per batch.
        hub_threshold: Minimum total connection weight to qualify as Layer 1.

    Returns:
        A BatchPlan with ordered batches across three layers.
    """
    # Extract short column names per dataset
    ds_columns: dict[str, set[str]] = {}
    ds_names: dict[str, str] = {}
    ds_by_id: dict[str, dict] = {}

    for ds in datasets:
        did = ds["id"]
        raw_name = ds.get("name", "")
        ds_names[did] = raw_name.rsplit(".", 1)[-1] if "." in raw_name else raw_name
        ds_by_id[did] = ds
        cols = set()
        for c in ds.get("columns", []):
            short = c.rsplit(".", 1)[-1].lower() if "." in c else c.lower()
            cols.add(short)
        ds_columns[did] = cols

    # Column -> datasets (join keys = columns in 2+ datasets)
    col_to_ds: dict[str, set[str]] = defaultdict(set)
    for did, cols in ds_columns.items():
        for col in cols:
            col_to_ds[col].add(did)

    join_keys = {col: ds_set for col, ds_set in col_to_ds.items() if len(ds_set) >= 2}
    join_key_stats = {col: len(ds_set) for col, ds_set in sorted(
        join_keys.items(), key=lambda x: -len(x[1])
    )[:30]}

    # Build weighted adjacency: shared join-key columns between dataset pairs
    edge_weight: dict[tuple[str, str], int] = defaultdict(int)
    for col, ds_set in join_keys.items():
        ds_list = list(ds_set)
        for i, d1 in enumerate(ds_list):
            for d2 in ds_list[i + 1:]:
                pair = (min(d1, d2), max(d1, d2))
                edge_weight[pair] += 1

    # Total connection weight per dataset
    ds_weight: dict[str, int] = defaultdict(int)
    for (d1, d2), w in edge_weight.items():
        ds_weight[d1] += w
        ds_weight[d2] += w

    # Greedy clustering: seed from highest-weight dataset, grow by strongest connection
    all_ds = set(ds_columns.keys())
    clustered: set[str] = set()
    clusters: list[tuple[list[str], float]] = []  # (dataset_ids, cohesion)

    # Break ties by dataset ID for determinism
    priority = sorted(all_ds, key=lambda d: (-ds_weight.get(d, 0), d))

    for seed in priority:
        if seed in clustered:
            continue

        cluster = [seed]
        clustered.add(seed)

        while len(cluster) < max_per_batch:
            # Score each unclustered dataset by total shared columns with cluster
            # Break ties by dataset ID for determinism
            candidates = []
            for did in sorted(all_ds - clustered):
                score = sum(
                    edge_weight.get((min(did, m), max(did, m)), 0)
                    for m in cluster
                )
                if score > 0:
                    candidates.append((-score, did))

            if not candidates:
                break

            candidates.sort()  # lowest -score (highest score) first, then by id
            best_candidate = candidates[0][1]
            cluster.append(best_candidate)
            clustered.add(best_candidate)

        # Compute internal cohesion (avg shared columns between members)
        internal_edges = 0
        n_pairs = len(cluster) * (len(cluster) - 1) / 2
        for i, d1 in enumerate(cluster):
            for d2 in cluster[i + 1:]:
                pair = (min(d1, d2), max(d1, d2))
                internal_edges += edge_weight.get(pair, 0)
        cohesion = internal_edges / max(1, n_pairs)

        clusters.append((cluster, cohesion))

    # Sweep up remaining isolated datasets
    remaining = all_ds - clustered
    if remaining:
        rem_list = sorted(remaining, key=lambda d: ds_names.get(d, ""))
        for i in range(0, len(rem_list), max_per_batch):
            chunk = rem_list[i:i + max_per_batch]
            clusters.append((chunk, 0.0))

    # Assign layers based on max connection weight in each cluster
    batches: list[Batch] = []
    layer1_count = 0
    layer2_count = 0
    layer3_count = 0

    for cluster_ds, cohesion in clusters:
        max_w = max((ds_weight.get(d, 0) for d in cluster_ds), default=0)
        if max_w >= hub_threshold:
            layer = 1
            layer1_count += 1
            name = f"core-{layer1_count}"
        elif any(ds_weight.get(d, 0) > 0 for d in cluster_ds):
            layer = 2
            layer2_count += 1
            name = f"domain-{layer2_count}"
        else:
            layer = 3
            layer3_count += 1
            name = f"isolated-{layer3_count}"

        batches.append(Batch(
            name=name,
            layer=layer,
            dataset_ids=cluster_ds,
            cohesion=cohesion,
        ))

    # Consolidate small batches: merge batches with <3 datasets within the same layer
    consolidated: list[Batch] = []
    pending_small: list[Batch] = []

    for b in batches:
        if len(b.dataset_ids) >= 3:
            consolidated.append(b)
        else:
            pending_small.append(b)

    # Merge small batches into groups of up to max_per_batch
    if pending_small:
        merged_ids: list[str] = []
        merged_layer = max(b.layer for b in pending_small)
        for sb in pending_small:
            merged_ids.extend(sb.dataset_ids)
            if len(merged_ids) >= max_per_batch:
                consolidated.append(Batch(
                    name=f"misc-{len(consolidated) + 1}",
                    layer=merged_layer,
                    dataset_ids=merged_ids[:max_per_batch],
                    cohesion=0.0,
                ))
                merged_ids = merged_ids[max_per_batch:]
        if merged_ids:
            consolidated.append(Batch(
                name=f"misc-{len(consolidated) + 1}",
                layer=merged_layer,
                dataset_ids=merged_ids,
                cohesion=0.0,
            ))

    batches = consolidated

    # Sort: Layer 1 first (highest cohesion first), then Layer 2, then Layer 3
    batches.sort(key=lambda b: (b.layer, -b.cohesion))

    return BatchPlan(
        batches=batches,
        ds_names=ds_names,
        join_key_stats=join_key_stats,
    )


# ── Concept-level clustering for topic discovery ──────────────────────


# Predicates that indicate concepts belong together in a topic.
# distinct-from is excluded because it marks domain boundaries.
COHESIVE_PREDICATES = {
    "informs", "derives-from", "correlates-with", "composes",
    "measured-by", "segmented-by", "filtered-by", "tracked-in",
}


@dataclass
class TopicCandidate:
    name: str
    description: str
    concept_ids: list[str]
    concept_names: list[str]
    hub_concept: str  # highest-degree concept in the cluster
    internal_edges: int


def cluster_concepts_into_topics(
    graph_dict: dict[str, Any],
    min_cluster_size: int = 2,
    max_cluster_size: int = 8,
) -> list[TopicCandidate]:
    """Discover topic candidates by clustering concept nodes.

    Uses connected-component detection on cohesive edges (informs,
    derives-from, correlates-with) between concept nodes. Large
    components are split by removing the weakest internal edge.

    Args:
        graph_dict: The concept graph as returned by ConceptGraph.to_dict().
        min_cluster_size: Minimum concepts per topic. Smaller clusters are
            merged into the nearest neighbour.
        max_cluster_size: Maximum concepts per topic. Larger clusters are
            split at the lowest-degree bridge node.

    Returns:
        Ordered list of TopicCandidates, largest first.
    """
    nodes = graph_dict.get("nodes", {})
    edges = graph_dict.get("edges", [])

    # Identify concept nodes
    concept_ids = {
        nid for nid, n in nodes.items() if n.get("node_type") == "concept"
    }

    # Build adjacency for concept-to-concept cohesive edges
    adj: dict[str, set[str]] = defaultdict(set)
    edge_count: dict[str, int] = defaultdict(int)

    for e in edges:
        src, tgt = e.get("source", ""), e.get("target", "")
        pred = e.get("predicate", "")
        if src in concept_ids and tgt in concept_ids and pred in COHESIVE_PREDICATES:
            adj[src].add(tgt)
            adj[tgt].add(src)
            edge_count[src] += 1
            edge_count[tgt] += 1

    # Connected components via BFS
    visited: set[str] = set()
    components: list[list[str]] = []

    for cid in sorted(concept_ids, key=lambda c: (-edge_count.get(c, 0), c)):
        if cid in visited:
            continue
        component = []
        queue = [cid]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            for nb in sorted(adj.get(node, set())):
                if nb not in visited:
                    queue.append(nb)
        components.append(component)

    # Also add isolated concepts (no cohesive edges to other concepts)
    for cid in sorted(concept_ids):
        if cid not in visited:
            components.append([cid])
            visited.add(cid)

    # Split oversized components greedily
    final_components: list[list[str]] = []
    for comp in components:
        if len(comp) <= max_cluster_size:
            final_components.append(comp)
        else:
            _split_component(comp, adj, edge_count, max_cluster_size, final_components)

    # Merge undersized components into their nearest neighbour.
    # First try direct concept-to-concept edges. If none, try entity-
    # mediated affinity (two concepts sharing edges to the same entity).
    entity_neighbours = _build_entity_affinity(concept_ids, edges, nodes)

    merged: list[list[str]] = []
    small: list[list[str]] = []
    for comp in final_components:
        if len(comp) >= min_cluster_size:
            merged.append(comp)
        else:
            small.append(comp)

    for sc in small:
        best_target = _find_nearest_cluster(sc, merged, adj)
        # Fallback: entity-mediated affinity
        if best_target is None:
            best_target = _find_nearest_cluster(sc, merged, entity_neighbours)
        if best_target is not None and len(merged[best_target]) + len(sc) <= max_cluster_size:
            merged[best_target].extend(sc)
        else:
            merged.append(sc)

    # Build TopicCandidates
    topics: list[TopicCandidate] = []
    for comp in merged:
        hub = max(comp, key=lambda c: edge_count.get(c, 0))
        hub_name = nodes[hub].get("name", "Unknown")

        # Count internal edges
        comp_set = set(comp)
        internal = sum(
            1 for e in edges
            if e["source"] in comp_set and e["target"] in comp_set
            and e.get("predicate", "") in COHESIVE_PREDICATES
        )

        concept_names = [nodes[c].get("name", "?") for c in comp]
        desc = f"Covers: {', '.join(concept_names[:5])}"
        if len(concept_names) > 5:
            desc += f" (+{len(concept_names) - 5} more)"

        topics.append(TopicCandidate(
            name=hub_name,
            description=desc,
            concept_ids=comp,
            concept_names=concept_names,
            hub_concept=hub,
            internal_edges=internal,
        ))

    # Sort: largest clusters first, then by internal edge count
    topics.sort(key=lambda t: (-len(t.concept_ids), -t.internal_edges))
    return topics


def _build_entity_affinity(
    concept_ids: set[str],
    edges: list[dict],
    nodes: dict[str, dict],
) -> dict[str, set[str]]:
    """Build concept-to-concept affinity via shared entity nodes.

    Two concepts are entity-affine if they both have edges to the same
    non-concept node (dataset, metric, event, column).
    """
    # concept -> set of entity IDs it connects to
    concept_entities: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        src, tgt = e.get("source", ""), e.get("target", "")
        if src in concept_ids and tgt not in concept_ids:
            concept_entities[src].add(tgt)
        elif tgt in concept_ids and src not in concept_ids:
            concept_entities[tgt].add(src)

    # Build affinity adjacency
    affinity: dict[str, set[str]] = defaultdict(set)
    concept_list = sorted(concept_ids)
    for i, c1 in enumerate(concept_list):
        for c2 in concept_list[i + 1:]:
            shared = concept_entities.get(c1, set()) & concept_entities.get(c2, set())
            if shared:
                affinity[c1].add(c2)
                affinity[c2].add(c1)
    return affinity


def _split_component(
    comp: list[str],
    adj: dict[str, set[str]],
    edge_count: dict[str, int],
    max_size: int,
    out: list[list[str]],
) -> None:
    """Split a large component into chunks of at most max_size.

    Uses iterative k-means-style partitioning: pick the two
    highest-degree nodes as seeds, then assign each remaining node
    to its nearest seed by BFS distance. Repeat on any oversized
    partition.
    """
    if len(comp) <= max_size:
        out.append(comp)
        return

    comp_set = set(comp)
    internal_adj = {c: adj.get(c, set()) & comp_set for c in comp}

    # Pick two seeds: highest-degree and the node farthest from it
    seed_a = max(comp, key=lambda c: (len(internal_adj[c]), c))
    dist_from_a = _bfs_distances(seed_a, internal_adj, comp_set)
    seed_b = max(comp, key=lambda c: (dist_from_a.get(c, 0), c))

    # Assign each node to its nearest seed
    dist_from_b = _bfs_distances(seed_b, internal_adj, comp_set)
    part_a: list[str] = []
    part_b: list[str] = []
    for c in comp:
        da = dist_from_a.get(c, 999)
        db = dist_from_b.get(c, 999)
        if da <= db:
            part_a.append(c)
        else:
            part_b.append(c)

    # If partitioning failed (one side is empty), just chunk sequentially
    if not part_a or not part_b:
        for i in range(0, len(comp), max_size):
            out.append(comp[i:i + max_size])
        return

    # Recurse on oversized partitions
    _split_component(part_a, adj, edge_count, max_size, out)
    _split_component(part_b, adj, edge_count, max_size, out)


def _bfs_distances(
    start: str,
    adj: dict[str, set[str]],
    valid: set[str],
) -> dict[str, int]:
    """BFS shortest distances from start within valid node set."""
    dist = {start: 0}
    queue = [start]
    while queue:
        node = queue.pop(0)
        for nb in adj.get(node, set()):
            if nb in valid and nb not in dist:
                dist[nb] = dist[node] + 1
                queue.append(nb)
    return dist


def _find_nearest_cluster(
    small: list[str],
    clusters: list[list[str]],
    adj: dict[str, set[str]],
) -> int | None:
    """Find the cluster with the most edges to the small component."""
    small_set = set(small)
    best_idx = None
    best_score = 0
    for i, cluster in enumerate(clusters):
        score = sum(
            1 for c in cluster
            for nb in adj.get(c, set())
            if nb in small_set
        )
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx
