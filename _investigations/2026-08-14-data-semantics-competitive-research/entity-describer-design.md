# Entity Describer - Pipeline Analysis and Agent Design

## Pipeline Ordering Analysis

### The Problem

The current M2 pipeline runs in this order:

```
Raw entities (names only) → Concept Extractor → Topic Creator
```

The Concept Extractor's prompt says: "Use descriptions as primary evidence. Column/dataset names are secondary." But in practice the data contradicts this:

| Entity type | In graph | Have descriptions | Coverage |
|-------------|----------|-------------------|----------|
| Datasets    | 99       | 0                 | 0%       |
| Columns     | 167      | 0                 | 0%       |
| Metrics     | 20       | 0                 | 0%       |
| Events      | 26       | 0                 | 0%       |
| **Total**   | **312**  | **0**             | **0%**   |

The source entities file (`opti_on_opti_entities.json`) has partial coverage:

| Entity type | In file | Have descriptions | Coverage |
|-------------|---------|-------------------|----------|
| Datasets    | 199     | 36                | 18%      |
| Columns     | 21,598  | 28                | 0.1%     |
| Metrics     | 236     | 117               | 50%      |
| Events      | 27      | 0                 | 0%       |

Even the existing descriptions are often low quality - terse notes like "correct too date for ARR figures" or partial phrases like "Only includes key features with tracking events included Q1 - Q4'25".

**The Concept Extractor is operating almost entirely on name inference.** This means:

1. **Cryptic names produce shallow concepts.** `DWH_CS_EXPERIMENT_METRICS_ALL_CUSTOMERS` is interpretable but `GS_GTM_OPS_WUMD_OPP_LEVEL` is not. The extractor guesses from abbreviations.
2. **Column semantics are invisible.** A column named `STATUS` could mean account status, subscription status, deal status, or experiment status. Without a description, the extractor assigns it to whichever concept seems most likely from context - often wrongly.
3. **Cross-domain ambiguity is unresolved.** `ARR` appears in sales, renewals, and product analytics with different scopes. The extractor has no signal to disambiguate beyond positional heuristics (which dataset contains the column).
4. **Edge reasoning is shallow.** The `segmented-by`, `derives-from`, and `measured-by` predicates are assigned based on column name patterns rather than understood semantics. A column named `REGION` gets `segmented-by` because it looks like a dimension, not because the agent understands what the column contains.

### The Correct Pipeline Order

```
Raw entities → Entity Describer → Concept Extractor → Topic Creator
         ↑                              ↓
         └──── (optional Round 2) ──────┘
```

**Descriptions first, then concepts.** This is what the delivery plan calls "fertiliser" - richer descriptions produce a richer concept graph.

The feedback loop is also valuable: after concepts are extracted, the Entity Describer can run a second pass using concept context to improve descriptions for entities it previously deferred on. For example, once the system knows there is a "Sales Pipeline" concept composed of datasets X, Y, Z, it can better describe columns in those datasets.

### Quality Impact Estimate

Based on the Opti-on-Opti data:

| Signal source | Current coverage | With Entity Describer |
|---------------|------------------|-----------------------|
| Dataset descriptions | 18% (36/199) | ~90% (high+medium confidence) |
| Column descriptions | 0.1% (28/21,598) | ~70% of columns in graph (167) |
| Metric descriptions | 50% (117/236) | ~85% (improve existing + generate missing) |
| Event descriptions | 0% (0/27) | ~80% (events often mirror dataset names) |

The quality uplift for the Concept Extractor would be substantial:
- **Better edge predicates.** With column descriptions, the extractor can distinguish `segmented-by` (a dimension used for grouping) from `filtered-by` (a boolean/categorical filter) from `derives-from` (a computed value).
- **Fewer singleton concepts.** Entities currently too opaque to cluster will become linkable.
- **Disambiguation at source.** Instead of the Topic Creator resolving "ARR" ambiguity at step 7, the Entity Describer resolves it at the column level: "ARR in this dataset refers to Annual Recurring Revenue for the customer's primary product line."

### What the Delivery Plan Already Says

The delivery plan (Stage 1) positions this as M1 work. The M1 tickets (AI-01 through AI-07) define:
- A single `describe-entities` agent with a `focus` parameter (AI-06)
- Confidence calibration with >90% accuracy at high confidence (AI-03)
- Follow-up question generation for low-confidence entities (AI-04)
- Multi-round context accumulation (AI-05)
- Domain-specific prompt variants as a stretch goal (AI-07)

The test harness we built for M2 can validate this agent the same way it validated the Concept Extractor and Topic Creator.

---

## Entity Describer Agent Design

### Agent Identity

| Field | Value |
|-------|-------|
| **Agent ID** | `oa-entity-describer` |
| **Description** | Generates human-readable descriptions for OA warehouse entities (datasets, columns, metrics, events) using structural context, naming patterns, and cross-entity inference. |
| **Model** | Claude Sonnet (cost-efficient for bulk generation) |
| **Output type** | JSON |

### Input Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `metadata_image` | Yes | JSON document containing entities to describe. Same format as the Concept Extractor input: `{ datasets: [...], metrics: [...], events: [...] }` |
| `focus` | No | Entity type to focus on: `dataset`, `column`, `metric`, `event`, or `all`. Default: `all`. When set, the agent only generates descriptions for the specified type but uses all entities as context. |
| `confirmed_descriptions` | No | JSON array of previously confirmed descriptions from earlier rounds. Format: `[{ entity_id, entity_type, description }]`. Used for multi-round accumulation. |
| `concept_context` | No | JSON document with extracted concepts and edges (from the Concept Extractor). When provided, the agent uses concept membership to improve descriptions. Enables the feedback loop. |
| `follow_up_answers` | No | JSON array of user answers to follow-up questions from a previous round. Format: `[{ question_id, answer }]`. |
| `industry_context` | No | Free text describing the customer's industry and business model. Helps with domain-specific terminology. |

### System Prompt

```
You are the Entity Describer for Optimizely Analytics. Your job is to generate
clear, accurate, one-paragraph descriptions for data warehouse entities
(datasets, columns, metrics, events) that currently lack descriptions or have
low-quality descriptions.

## Your role

You are writing descriptions that will be read by:
1. Business analysts who need to understand what data is available
2. AI agents (the Concept Extractor) that will use descriptions to identify
   business concepts and semantic relationships
3. Admins who will review and approve your descriptions before they are applied

## Input context

You receive a metadata image containing datasets with their columns, metrics,
and events. Some entities already have descriptions - use these as context to
infer descriptions for related entities. Pay attention to:

- **Naming conventions.** Prefixes like `DWH_`, `GS_`, `SST_` indicate source
  systems. Folder paths like `Analytics & Data.Insight & Analysis.02 Sales`
  reveal organizational hierarchy.
- **Column co-occurrence.** Columns within the same dataset share a domain.
  If one column has a description, nearby columns can be inferred.
- **Cross-entity references.** A metric named "Bookings ASP" in the
  "02 Sales" folder relates to datasets containing booking columns.
- **Structural patterns.** ID columns, date columns, flag columns, and
  aggregation columns follow predictable patterns.

## Description quality standards

Each description must:
1. **State what the entity contains or measures** - not just restate the name
2. **Identify the business domain** - sales, marketing, product, CS, etc.
3. **Note the grain/level** for datasets - opportunity-level, account-level,
   daily, monthly, etc.
4. **Clarify abbreviations** - expand GTM, ARR, ASP, DWH, CS, FX, etc.
5. **Distinguish from similar entities** - if multiple entities have similar
   names, explain what makes this one different

Bad: "Contains sales data"
Good: "Opportunity-level sales pipeline dataset from the GTM forecasting model.
Each row represents one open or closed opportunity with stage progression,
forecast category, territory assignment, and deal aging metrics. Used for
pipeline reviews and quarterly forecasting."

Bad: "Stage name"
Good: "Current sales stage of the opportunity (e.g. Prospecting, Qualification,
Proposal, Closed Won). Reflects the latest stage update from Salesforce."

## Confidence assessment

For each description, self-assess confidence:

- **high** - The entity's purpose is clear from its name, context, and
  structural position. You are >90% confident the description is accurate.
  Example: a column named `OPPORTUNITY_CLOSE_DATE` in a sales pipeline dataset.
- **medium** - The entity's purpose is likely but relies on inference from
  naming patterns or sibling entities. You are 70-90% confident.
  Example: a column named `FCST_CAT` in a sales dataset (likely "Forecast
  Category" but could be something else).
- **low** - The entity's purpose is ambiguous. Multiple interpretations are
  plausible. You should generate a description for the most likely
  interpretation but flag it for human review.
  Example: a column named `FLAG_1` with no surrounding context.
- **skip** - The entity is too opaque to describe without domain knowledge.
  Do not guess. Instead, generate a follow-up question.
  Example: a column named `XYZ_CODE` in a dataset with no other clues.

## Follow-up questions

For entities you cannot describe (low confidence or skip), generate a
follow-up question that:
1. References the specific entity by name and ID
2. Explains what you can infer and what is missing
3. Offers 2-4 multiple-choice options when possible
4. Is actionable - answering it should resolve the ambiguity

## Improving existing descriptions

When an entity already has a description, evaluate it:
- If it is accurate and complete, keep it (set `action: "keep"`)
- If it is accurate but too terse, expand it (set `action: "improve"`)
- If it is inaccurate or misleading, replace it (set `action: "replace"`)

When improving, preserve the original meaning and add specificity. Do not
contradict what the original author wrote unless it is clearly wrong.

## Multi-round context

If `confirmed_descriptions` are provided, use them as ground truth. They
represent human-reviewed descriptions from previous rounds. Leverage them to:
- Describe related entities with higher confidence
- Resolve ambiguities that blocked previous rounds
- Maintain consistency with the established vocabulary

If `concept_context` is provided, use concept membership to improve
descriptions. An entity linked to the "Sales Pipeline" concept should be
described in sales pipeline terms.

If `follow_up_answers` are provided, incorporate the answers into your
descriptions for the affected entities. The answer should raise your
confidence to at least medium.

## Output format

Return a JSON object matching the schema below. Do not include any text
outside the JSON block.
```

### Output Schema

```json
{
  "descriptions": [
    {
      "entity_id": "string - the entity's ID from the metadata image",
      "entity_type": "string - dataset | column | metric | event",
      "entity_name": "string - the entity's name (for human readability)",
      "parent_dataset": "string | null - for columns, the parent dataset name",
      "description": "string - the generated description (1-3 sentences)",
      "confidence": "string - high | medium | low",
      "action": "string - generate | improve | replace | keep",
      "needs_review": "boolean - true if confidence is low or action is replace",
      "review_reason": "string | null - why human review is needed"
    }
  ],
  "follow_up_questions": [
    {
      "question_id": "string - unique ID for this question (q-001, q-002, ...)",
      "entity_ids": ["string - entity IDs affected by this question"],
      "question": "string - the question to ask the human",
      "context": "string - what you can infer and what is missing",
      "options": [
        {
          "label": "string - option label (a, b, c, ...)",
          "text": "string - option text",
          "implication": "string - what this answer would mean for the description"
        }
      ]
    }
  ],
  "summary": {
    "total_entities": "number - total entities in input",
    "generated": "number - new descriptions generated",
    "improved": "number - existing descriptions improved",
    "replaced": "number - existing descriptions replaced",
    "kept": "number - existing descriptions kept as-is",
    "skipped": "number - entities deferred (follow-up questions generated)",
    "high_confidence": "number",
    "medium_confidence": "number",
    "low_confidence": "number"
  }
}
```

### Batching Strategy

The 300s Hypatia SSE timeout constrains how many entities we can process per call. Based on the Concept Extractor experience:

| Entity type | Typical count per app | Batch size | Estimated rounds |
|-------------|----------------------|------------|------------------|
| Datasets    | 50-200               | 15-20 datasets (with columns) | 10-13 |
| Columns     | N/A (batched with parent dataset) | - | - |
| Metrics     | 50-250               | 40-50 metrics | 5-6 |
| Events      | 10-50                | All at once | 1 |

**Datasets are the bottleneck** because each dataset carries its columns (average 114 columns in Opti-on-Opti). A batch of 15 datasets with columns is ~15K-25K tokens of input.

Batching order:
1. **Events first** (smallest batch, provides domain signal for later batches)
2. **Metrics second** (half already have descriptions, provides measurement vocabulary)
3. **Datasets + columns last** (largest batch, benefits from event and metric context)

Within each entity type, batch by domain affinity:
- Group datasets by folder path prefix (e.g. all `Analytics & Data.Insight & Analysis.02 Sales.*` together)
- This gives the agent maximum cross-entity inference within each batch

### Interaction Model

The Entity Describer uses a **draft-review-refine** loop rather than a step-by-step checklist:

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Round 1: Generate descriptions                                 │
│  ├─ Batch entities by type and domain                           │
│  ├─ Call agent for each batch                                   │
│  ├─ Collect all descriptions + follow-up questions              │
│  └─ Present review summary to user                              │
│       ├─ High confidence: auto-accept (show count)              │
│       ├─ Medium confidence: show for quick scan                 │
│       ├─ Low confidence: show for detailed review               │
│       └─ Follow-up questions: present interactively             │
│                                                                 │
│  Round 2: Refine with feedback                                  │
│  ├─ Feed confirmed descriptions as context                      │
│  ├─ Feed follow-up answers                                      │
│  ├─ Re-run for skipped/low-confidence entities                  │
│  └─ Present new descriptions for review                         │
│                                                                 │
│  Round 3+ (optional): Concept-enriched refinement               │
│  ├─ After Concept Extractor runs, feed concept_context          │
│  ├─ Re-describe entities using concept membership               │
│  └─ Focus on entities whose concept assignment was uncertain     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Auto-accept mode** (for harness batch runs): accept all high+medium confidence descriptions, skip follow-up questions, generate a report of what was deferred.

**Interactive mode** (for production use): present each confidence tier for review, ask follow-up questions, accumulate confirmed descriptions across rounds.

### Harness CLI Command

```bash
# Full run (all entity types, interactive review)
python3 -m harness --instance $IID describe-entities \
  --agent-id oa-entity-describer \
  --entities harness/opti_on_opti_entities.json

# Focused run (datasets only, auto-accept)
python3 -m harness --instance $IID describe-entities \
  --agent-id oa-entity-describer \
  --entities harness/opti_on_opti_entities.json \
  --focus dataset \
  --auto

# Round 2 with confirmed descriptions from Round 1
python3 -m harness --instance $IID describe-entities \
  --agent-id oa-entity-describer \
  --entities harness/opti_on_opti_entities.json \
  --confirmed harness/output/confirmed_descriptions.json

# With concept context (post-extraction refinement)
python3 -m harness --instance $IID describe-entities \
  --agent-id oa-entity-describer \
  --entities harness/opti_on_opti_entities.json \
  --concept-graph harness/output/concept_graph.json
```

### Output Files

```
harness/output/
  descriptions/
    round_1_events.json         ← raw agent output
    round_1_metrics_batch_1.json
    round_1_metrics_batch_2.json
    round_1_datasets_batch_1.json
    ...
    confirmed_descriptions.json ← human-reviewed, merged across rounds
    follow_up_questions.json    ← unanswered questions for next round
    review_report.md            ← human-readable summary
  enriched_entities.json        ← original entities + descriptions merged
```

The `enriched_entities.json` becomes the input for the Concept Extractor, replacing the raw `opti_on_opti_entities.json`.

---

## Comparison with M1 Ticket Design

The M1 tickets (AI-01 through AI-07) describe a production implementation in `opal-app` that communicates via WebSocket. Our test harness agent is the **validation prototype** for those tickets:

| Aspect | M1 Production Design | Test Harness Agent |
|--------|---------------------|--------------------|
| Infrastructure | Java WS Client in OA backend | Python HTTP+SSE via Hypatia |
| Agent location | Opal specialized agent | Same (Opal specialized agent) |
| Storage | OA PostgreSQL (description_candidates table) | Local JSON files |
| Review UI | Frontend admin panel | CLI interactive mode |
| Multi-round | Backend orchestration with DB state | Harness CLI with file-based state |
| Confidence gating | Backend threshold config | Harness auto-accept logic |

The agent prompt is the same in both cases. The harness lets us validate the prompt quality before building the production infrastructure.

---

## Open Questions

1. **Column batching.** Should columns be sent with their parent dataset (more context, larger payload) or separately (smaller payload, less context)? Recommendation: with parent dataset, capped at 15-20 datasets per batch.

2. **Existing description handling.** The M1 tickets mention `action: keep | improve | replace`. Should the agent always evaluate existing descriptions, or only when explicitly asked? Recommendation: always evaluate - the 117 metric descriptions with existing text are a good test of the improve/replace logic.

3. **Model choice.** The M1 tickets don't specify a model. Sonnet is cost-efficient for bulk generation but Opus may produce better disambiguation. Recommendation: start with Sonnet, compare quality on a 2-batch sample with Opus. Switch if quality gap is significant.

4. **Column description depth.** 21,598 columns is far too many to describe individually. The graph only contains 167 columns (those the Concept Extractor selected as relevant). Should the Entity Describer process all columns or only graph-relevant ones? Recommendation: start with graph-relevant columns, expand to full column set only if the Concept Extractor's second pass requests it.
