# Data Semantics Competitive Research

**Date:** 2026-08-14
**Context:** Joe Timko proposed two features (App Routing, Semantic Subjects) after researching how competitors handle data semantics for conversational analytics. This investigation captures the competitive research and synthesis ahead of a prioritisation meeting on 2026-08-20 (Joe, Joao, Charlie).

## Files

| File | Purpose |
|------|---------|
| `competitive-research.md` | Deep-dive into each competitor's approach based on Joe's shared links |
| `synthesis.md` | Cross-cutting patterns, comparison matrix, and implications for OA |
| `topic-design.md` | Design draft for Semantic Topics - concepts graph, three metadata layers, trust hierarchy, event bus, scoping |
| `architecture-comparison.md` | Deep architectural comparison of all competitors (Databricks, Omni, Hex, Snowflake, Sigma, Anthropic) vs OA design |
| `conceptual-diagram.md` | Visual diagrams of the full system: three layers, graph, trust hierarchy, topics as subgraphs, evolution lifecycle, event bus, storage |
| `delivery-plan.md` | Multi-stage delivery plan: 6 stages from AI description service through evolution pipeline, with role ownership and success criteria |
| `m2-agent-drafts.md` | Concept Extractor and Topic Creator agent prompt templates and output schemas |
| `stratified-extraction-design.md` | Deterministic stratified extraction algorithm, M2 retrofit guide, production ConceptGraphService mapping |
| `entity-describer-design.md` | Pipeline ordering analysis (descriptions before concepts), Entity Describer agent prompt, output schema, batching strategy |
| `concept-catalogue.md` | Prose listing of all 45 extracted concepts with descriptions, related entities, and edge counts |
| `concept-graph.html` | Interactive Cytoscape.js graph with topic lenses, concept/topic prose, business rules, disambiguation |
| `harness/` | Python test harness for M2 agents: Hypatia SSE client, local concept graph, stratified batch extraction, entity description |

## Harness

The `harness/` directory is a Python test harness that validates the M2 agent
prompts end-to-end before building backend infrastructure. Key commands:

```bash
# Single extraction run
python3 -m harness --instance $IID extract --agent-id oa-concept-extractor ...

# Stratified extraction (relationship-based batching, covers full warehouse)
python3 -m harness --instance $IID stratified-extract --agent-id oa-concept-extractor ...

# Interactive topic creation (8-step checklist)
python3 -m harness --instance $IID create-topic --agent-id oa-topic-creator ...

# Entity description generation (batch, auto-accept)
python3 -m harness --instance $IID describe-entities --agent-id oa-entity-describer \
  --entities harness/opti_on_opti_entities.json --auto

# Entity description generation (focused on datasets, with concept context)
python3 -m harness --instance $IID describe-entities --agent-id oa-entity-describer \
  --entities harness/opti_on_opti_entities.json --focus dataset \
  --concept-graph harness/output/concept_graph.json

# Auto-generate topics from concept graph
python3 -m harness --instance $IID generate-topics --agent-id oa-topic-creator \
  --entities harness/opti_on_opti_entities.json
```

### Recommended pipeline order

```
1. describe-entities  →  enriched_entities.json (descriptions for all entity types)
2. extract / stratified-extract  →  concept_graph.json (using enriched entities)
3. generate-topics  →  topics/*.json (using concept graph)
```

See `entity-describer-design.md` for the full analysis of why descriptions
should come before concepts, and `stratified-extraction-design.md` for the
deterministic batching algorithm.

## Related

- `_projects/data-semantics-chat/` - Joe's message analysis, three-layer framework, semantic tree mapping
- Joe's original message and the Opal Data Analyst skill (Scott Levine's context dump) are the triggers
- Meeting transcript at `~/Desktop/data_semantics_chat.md`
