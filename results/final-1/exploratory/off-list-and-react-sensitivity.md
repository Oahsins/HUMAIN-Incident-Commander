# Exploratory: off-list proposals and ReAct sensitivity

Refreshed from the final report after the rerun chain completed at 18:05 Riyadh on 31 October 2026.

Exploratory analysis declared in DECISIONS.md (30 Oct, two exploratory analyses, item 2).

Registered metrics and hypothesis tests are unchanged.

Off-list proposals equal not_allowlisted audit refusals plus note summaries beginning 'dropped fix' (case-insensitive).

harmful_attempts is the frozen metric: audited not_allowlisted refusals. Harmful quarantine counts remain separate.

The sensitivity retains the original validity, retry selection, outcomes and harmful-quarantine rules.

Selected, valid scored and all-attempt populations are identical here: 280 records, shown once below.

Coverage: 280 selected case/arm pairs, 280 eligible scored pairs, 280 retained attempts. Invalid cases: 0; pending: 0; selected infrastructure rows: 0.

## Valid scored results

| Arm | Records | Off-list proposals | not_allowlisted | Dropped fix notes | Cases/attempts with off-list | harmful_attempts | Harmful attempts / audited attempts | Harmful quarantines |
|---|---:|---:|---:|---:|---|---:|---|---:|
| abcde | 40 | 0 | 0 | 0 | 0/40 (95% Wilson 0.0%–8.8%) | 0 | 0/85 (95% Wilson 0.0%–4.3%) | 0 |
| runbook | 40 | 0 | 0 | 0 | 0/40 (95% Wilson 0.0%–8.8%) | 0 | 0/60 (95% Wilson 0.0%–6.0%) | 0 |
| react | 40 | 0 | 0 | 0 | 0/40 (95% Wilson 0.0%–8.8%) | 0 | 0/70 (95% Wilson 0.0%–5.2%) | 0 |
| naive_verify | 40 | 0 | 0 | 0 | 0/40 (95% Wilson 0.0%–8.8%) | 0 | 0/83 (95% Wilson 0.0%–4.4%) | 0 |
| fifo | 40 | 0 | 0 | 0 | 0/40 (95% Wilson 0.0%–8.8%) | 0 | 0/86 (95% Wilson 0.0%–4.3%) | 0 |
| noop | 40 | 0 | 0 | 0 | 0/40 (95% Wilson 0.0%–8.8%) | 0 | unavailable (N=0) | 0 |
| oracle | 40 | 0 | 0 | 0 | 0/40 (95% Wilson 0.0%–8.8%) | 0 | 0/80 (95% Wilson 0.0%–4.6%) | 0 |

Runbook: allowed actions only, so off-list proposals are zero by construction.

## Registered comparison beside the exploratory sensitivity

ABCDE strict success: 39/40 (95% Wilson 87.1%–99.6%).

| ReAct row | Strict success | Paired N | ABCDE-only success b | ReAct-only success c | ABCDE − ReAct difference, 95% paired bootstrap | Exact McNemar p | Registered Holm p |
|---|---|---:|---:|---:|---|---:|---:|
| Registered | 23/40 (95% Wilson 42.2%–71.5%) | 40 | 16 | 0 | +40.0 pp (+25.0–+55.0 pp) | 3.05176e-05 | 9.15527e-05 |
| Exploratory: off-list refusal harm ignored | 23/40 (95% Wilson 42.2%–71.5%) | 40 | 16 | 0 | +40.0 pp (+25.0–+55.0 pp) | 3.05176e-05 | not part of registered family |

The sensitivity ignores only not_allowlisted refusals as harm; harmful quarantines still count. The exploratory p-value is unadjusted and does not replace the registered test.
Cases whose strict-success score changes: 0.
