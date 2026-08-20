"""Local concept graph - accumulates concepts and edges from extraction runs.

The graph is a simple node+edge structure stored as JSON. It is the local
stand-in for what the ConceptGraphService would manage in production.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


VALID_NODE_TYPES = {"concept", "dataset", "column", "event", "metric"}

VALID_PREDICATES = {
    # Compositional
    "composes", "derives-from", "extracts-from", "part-of", "contains",
    # Descriptive
    "describes", "represents", "specialises",
    # Disambiguation
    "equivalent-to", "distinct-from",
    # Data binding
    "tracked-in", "signalled-by", "measured-by",
    # Reasoning
    "informs", "correlates-with",
    # Extra descriptive used in agent output
    "segmented-by", "filtered-by",
}


@dataclass
class Node:
    id: str
    name: str
    node_type: str  # concept, dataset, column, event, metric
    trust: str = "ai-generated"
    confidence: str = "medium"
    description: str = ""
    execution_hints: dict[str, str] = field(default_factory=dict)


@dataclass
class Edge:
    source: str  # node id
    target: str  # node id
    predicate: str
    reasoning: str = ""


class ConceptGraph:
    """In-memory concept graph with JSON persistence."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def add_from_extraction(self, extraction_output: dict[str, Any]) -> None:
        """Merge concept extractor output into the graph.

        The extraction output follows the schema from m2-agent-drafts.md:
        {
            "concepts": [{name, description, confidence, trust, edges: [...]}],
            "disambiguation": [{concept_a, concept_b, predicate, explanation}],
            "summary": {...}
        }
        """
        concepts = extraction_output.get("concepts", [])
        for concept in concepts:
            concept_id = f"c-{uuid.uuid4().hex[:8]}"
            node = Node(
                id=concept_id,
                name=concept["name"],
                node_type="concept",
                trust=concept.get("trust", "ai-generated"),
                confidence=concept.get("confidence", "medium"),
                description=concept.get("description", ""),
                execution_hints=concept.get("execution_hints", {}),
            )
            self.add_node(node)

            for edge_data in concept.get("edges", []):
                target_id = edge_data.get("target_id", "")
                target_type = edge_data.get("target_type", "")
                target_name = edge_data.get("target_name", "")

                # Ensure the target node exists (entities from the app)
                if target_id and target_id not in self.nodes:
                    self.add_node(Node(
                        id=target_id,
                        name=target_name,
                        node_type=target_type,
                        trust="human-authored",
                    ))

                self.add_edge(Edge(
                    source=concept_id,
                    target=target_id,
                    predicate=edge_data.get("predicate", "composes"),
                    reasoning=edge_data.get("reasoning", ""),
                ))

        # Disambiguation edges
        for dis in extraction_output.get("disambiguation", []):
            concept_a_name = dis.get("concept_a", "")
            concept_b_name = dis.get("concept_b", "")
            # Look up by name
            a_id = self._find_by_name(concept_a_name)
            b_id = self._find_by_name(concept_b_name)
            if a_id and b_id:
                self.add_edge(Edge(
                    source=a_id,
                    target=b_id,
                    predicate=dis.get("predicate", "distinct-from"),
                    reasoning=dis.get("explanation", ""),
                ))

    def _find_by_name(self, name: str) -> str | None:
        for node in self.nodes.values():
            if node.name.lower() == name.lower():
                return node.id
        return None

    def get_concepts(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.node_type == "concept"]

    def get_edges_for(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id or e.target == node_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {k: asdict(v) for k, v in self.nodes.items()},
            "edges": [asdict(e) for e in self.edges],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> ConceptGraph:
        data = json.loads(path.read_text())
        graph = cls()
        for nid, ndata in data.get("nodes", {}).items():
            graph.add_node(Node(**ndata))
        for edata in data.get("edges", []):
            graph.add_edge(Edge(**edata))
        return graph

    def as_graph_context(self, compact: bool = True) -> str:
        """Serialise for the Topic Creator's graph_context variable.

        Args:
            compact: If True, include only concept nodes and their edges
                (not full entity nodes). This keeps the payload under ~10K
                chars. Entity details are provided separately via app_entities.
        """
        if not compact:
            return json.dumps(self.to_dict(), indent=2)

        # Compact: concepts + concept-to-entity edge summaries
        concepts = []
        for n in self.nodes.values():
            if n.node_type != "concept":
                continue
            edges_out = []
            for e in self.edges:
                if e.source == n.id:
                    target = self.nodes.get(e.target)
                    target_name = target.name if target else e.target
                    target_type = target.node_type if target else "unknown"
                    edges_out.append({
                        "target": target_name,
                        "type": target_type,
                        "predicate": e.predicate,
                    })
                elif e.target == n.id:
                    source = self.nodes.get(e.source)
                    source_name = source.name if source else e.source
                    source_type = source.node_type if source else "unknown"
                    edges_out.append({
                        "source": source_name,
                        "type": source_type,
                        "predicate": e.predicate,
                    })
            concepts.append({
                "id": n.id,
                "name": n.name,
                "description": n.description[:200] if n.description else "",
                "confidence": n.confidence,
                "edges": edges_out,
            })

        return json.dumps({"concepts": concepts}, separators=(",", ":"))

    def summary(self) -> str:
        concepts = self.get_concepts()
        return (
            f"{len(concepts)} concepts, "
            f"{len(self.nodes) - len(concepts)} entities, "
            f"{len(self.edges)} edges"
        )
