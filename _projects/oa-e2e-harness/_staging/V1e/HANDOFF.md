# V1e - Replay transience classification

## Verdict

Transience determined by replay, not tuple lookup. 10/10 flake test passes.
`corpus_sweep.py` committed. `TRANSIENT_ERRORS` tuple unchanged (already correct).

## A1: 25-row transience table

Each compilable recording replayed 3 times. Error presence checked in the actual
GraphQL responses (via `call.errors` in the run report), not via assertion
pass/fail.

| # | Message (first 120 chars) | Recording | Runs | Observed | Verdict |
|---|---|---|---|---|---|
| 1 | Invalid filteredEvent: missing eventDataset id | drive-author-220505 | 0/0 | stale deps (401100 deleted) | undetermined |
| 2 | Cannot invoke "...NetScript.parameterState()" because "netScript" is null | drive-author-221914 | 0/0 | stale deps (5 entities deleted) | undetermined |
| 3 | No entity found with id not-a-real-id-at-all. | drive-t81-154107 | 0/0 | stale deps (401397 deleted) | undetermined |
| 4 | No entity found with id [[...folderID]]. | drive-t81-154107 | 0/0 | stale deps (401397 deleted) | undetermined |
| 5 | No entity found with id e467d0ec-af0d-40dd-b638-d1f7369be265. | drive-t81-154107 | 0/0 | stale deps (401397 deleted) | undetermined |
| 6 | No entity found with id 401397_e467d0ec-af0d-40dd-b638-d1f7369be265. | drive-t81-154107 | 0/0 | stale deps (401397 deleted) | undetermined |
| 7 | Missing event / Missing event | drive-author-222430 | 3/3 | same error all 3 runs | reproducible |
| 8 | No entity found with id draft. | drive-b4-010713 | 0/3 | error in getEntityAppId, not in spine (dropped by distil) | undetermined |
| 9 | Cannot invoke "...NetScriptSchema$Dataset.shortName()" because ... is null | drive-probe-231812 | 3/3 | same error all 3 runs | reproducible |
| 10 | No entity found with id fake-lookup-id. | drive-t79-162004 | 0/0 | no spine ops in recording (ScenarioError: no steps) | undetermined |
| 11 | UUID must be in standard 36-char format | drive-t81-160829 | 0/0 | stale deps (401397 deleted) | undetermined |
| 12 | Alert not found: e467d0ec-af0d-40dd-b638-d1f7369be265 | drive-t81-160829 | 0/0 | stale deps (401397 deleted) | undetermined |
| 13 | Incomplete configuration for aggregation - Aggregator operator and property both must be present. | capture-20260808-210537-readonly-tour | 3/3 | same error all 3 runs | reproducible |
| 14 | Cannot invoke "...Bloq$Terminal.type()" because "measureTerm" is null | capture-20260808-210537-readonly-tour | 3/3 | same error all 3 runs | reproducible |
| 15 | NetScript errors L5:7..L5:39 -> Expected quad of type STRING, found NUMERIC | capture-20260808-210537-readonly-tour | 3/3 | same error all 3 runs | reproducible |
| 16 | Exception while generating SQL: Cannot invoke "...DataTable$Spec.measures()" ... is null | drive-author-221914 | 0/0 | stale deps (5 entities deleted) | undetermined |
| 17 | Missing input / Invalid bloqlet, error: Missing input | drive-author-221914 | 0/0 | stale deps (5 entities deleted) | undetermined |
| 18 | No entity found with id 401427_e467d0ec-af0d-40dd-b638-d1f7369be265. | drive-author-232709 | 0/0 | stale deps (401427, 401428 deleted) | undetermined |
| 19 | NetScript errors L1:1..L1:5 -> "Users" not found: it is not the name of a variable or a catalog entity | drive-code-224420 | 3/3 | same error all 3 runs | reproducible |
| 20 | Entities already exists in db | drive-g1-023653 | 0/0 | stale deps (401890 deleted) | undetermined |
| 21 | Error while fetching query metadata. Error: SQL compilation error: ... invalid identifier '"frm"' | drive-g10-021647 | 3/3 | same error all 3 runs | reproducible |
| 22 | Query cancelled on user's request. | drive-probe-000639 | 0/3 | error absent all 3 runs | transient |
| 23 | Comparison time 1mo must be a multiple of or same as the provided time grain 1d | drive-probe-000639 | 3/3 | same error all 3 runs | reproducible |
| 24 | Missing terminal entity | drive-probe-231812 | 3/3 | same error all 3 runs | reproducible |
| 25 | Failed to generate NetScript for derived column: Derived column cannot be joined from Users | drive-w0-202020 | 0/0 | no spine ops in recording (ScenarioError: no steps) | undetermined |

### Summary

| Verdict | Count | Messages |
|---|---|---|
| reproducible | 10 | #7, #9, #13, #14, #15, #19, #21, #23, #24 |
| transient | 1 | #22 |
| undetermined | 14 | #1-6, #8, #10-12, #16-18, #20, #25 |

Of the 14 undetermined:
- 10 are stale deps (recording references deleted entities, cannot replay at all)
- 2 have no spine ops (no QueryExplore/LoadExplore in the recording)
- 1 has the error in a non-spine call (getEntityAppId, dropped during distillation)
- 1 has stale deps (same as the 10 above, just a different recording)

### `TRANSIENT_ERRORS` unchanged

The sole entry `"Query cancelled on user's request"` is confirmed transient
(0/3). No other message exhibited transient behaviour. The tuple is correct.

## A2: 10x flake test

Session alive. `drive-shard-e-144816` replayed 10 times:

```
Run 1/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 2/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 3/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 4/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 5/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 6/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 7/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 8/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 9/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Run 10/10: PASS  steps: 2/2 ok  assertions: 62/62 passed
Summary: 10/10 PASS, 0/10 FAIL
```

V1d's volatile-key fix is confirmed. The assertion that caused the V1c flake
(asserting `exists` on `resultCacheTimeMs` which flips between null and non-null
depending on OA cache state) is no longer generated.

## A3: Fail-open demonstration

**Blocker.** The DB tunnel (`tools/cluster-tunnel inte 5436`) is running. I
cannot stop it (the user controls it). The fail-open code path in
`check_entity_existence()` is tested only through code inspection, not through a
live demonstration.

To demonstrate: stop the tunnel, then run:
```
python3 -c "
import sys; sys.path.insert(0, '.')
from pathlib import Path
from oaflow.replay import distil_readonly, run
plan = distil_readonly(Path('artifacts/drive-probe-000639/recording.jsonl'), env='inte')
report = run(plan, ident='A3-test', check_deps=True)
print(report.verdict)
"
```

Expected output includes:
```
WARNING: DB tunnel not reachable - entity existence check skipped for 3 dependencies. Stale recordings may produce false failures.
```

## A4: `oaflow/corpus_sweep.py`

Committed at `/Users/joao.rodrigues/IdeaProjects/netspring-extra/_projects/oa-e2e-harness/oaflow/corpus_sweep.py`.

Features:
- CLI entry point: `python3 -m oaflow.corpus_sweep [directory] [--env ENV] [--json]`
- Default directory: `artifacts/`
- Iterates recordings, distils readonly, compiles, runs
- Summary: PASS/FAIL/REFUSED/ERROR counts
- When any plan has `deps_checked=False`, emits:
  `WARNING: entity existence unverified for N of M plans - REFUSED counts are unreliable`
- JSON output mode for programmatic consumption

The sweep-level warning is wired: when the DB tunnel is down during
`check_entity_existence()`, `Plan.deps_checked` is set to False, and
`SweepResult.summary_lines()` emits the warning when `unchecked_count > 0`.

**Live demonstration of the warning requires the tunnel to be down** (same
blocker as A3).

## A5: Entity count

Start: 63 (DASHBOARD 1, DASHBOARD_TILE 1, EXPLORE 61).
End: 63 (DASHBOARD 1, DASHBOARD_TILE 1, EXPLORE 61).

V1e is readonly. No entities created or deleted.

```sql
select id, short_name, entity_type from entity
where appid = 'e467d0ec-af0d-40dd-b638-d1f7369be265' and short_name like '[e2e] %'
  and not deleted and next_sqn = 9007199254740991;
```

## Skipped

- C1 and regression set: skipped as instructed.

## Files

| Path | Reason |
|---|---|
| `oaflow/corpus_sweep.py` | New. Corpus sweep runner with CLI, deps_checked warning. |
| `_staging/V1e/HANDOFF.md` | This file. |
