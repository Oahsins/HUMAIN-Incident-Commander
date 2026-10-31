# Evaluation report: final-1

> **Scope: Held-out evaluation**

## What this run is

- **Run:** `final-1`
- **Stage:** Sealed exam (held-out cases)
- **Condition:** `default`
- **Arms:** ABCDE agent (n = 40), Scripted runbook (no AI) (n = 40), ReAct (free-form agent) (n = 40), Naive verify (ablation) (n = 40), FIFO order (ablation) (n = 40), No-op (reference) (n = 40), Oracle (reference) (n = 40)
- **Model:** anthropic:claude-opus-5-5
- **Code:** commit `0e58fe93090f`
- **Freeze hashes (first 12 characters):** agent `9c27cb684997`, baseline `55082984be2b`, scenarios/heldout/SEALED.json `f2ed58bc0e98`, scorer `e29e6c9bbd40`, settings `f16a6d6879e3`, system `9917f1ab1018`
- 8 other manifest field(s) not shown in this report.

## Headline: the system against the scripted runbook

The scripted runbook uses no AI. Where it ties or wins, that is reported here first.

> The runbook wins on 0/40 (95% Wilson 0.0%–8.8%) paired cases and ties on 20/40 (95% Wilson 35.2%–64.8%).

| Family | Comparison | Endpoint | Pairs | b | c | Difference [95% CI] | p | p (adjusted) | Method |
|---|---|---|---|---|---|---|---|---|---|
| primary | ABCDE vs runbook | case success | 40 | 20 | 0 | +50 pts [+35 pts to +65 pts] | <0.001 | unavailable | Exact McNemar; paired bootstrap |
| secondary | ABCDE vs runbook, named held-out or blind | case success | 28 | 20 | 0 | +71 pts [+54 pts to +86 pts] | <0.001 | <0.001 | Exact McNemar; paired bootstrap |
| secondary | ABCDE vs runbook | user-impact seconds | 40 | unavailable | unavailable | unavailable [unavailable] | 0.098 | 0.197 | Wilcoxon signed-rank |

b: pairs where the endpoint is present for the first-named arm and absent for the second; c: the reverse. For case success, b counts pairs only the first arm succeeded on. For false all-clear (lower is better), b counts pairs where only the first arm made the false claim, so a larger b is worse for the first arm. Difference is first minus second: percentage points for rates, seconds for user impact. Rows without b, c or an interval (such as the Wilcoxon test on user-impact seconds) show unavailable.

## All paired comparisons

Arms are compared only on identical cases. The primary comparison is tested at alpha 0.05; secondary comparisons are Holm-adjusted as one family.

| Family | Comparison | Endpoint | Pairs | b | c | Difference [95% CI] | p | p (adjusted) | Method |
|---|---|---|---|---|---|---|---|---|---|
| primary | ABCDE vs runbook | case success | 40 | 20 | 0 | +50 pts [+35 pts to +65 pts] | <0.001 | unavailable | Exact McNemar; paired bootstrap |
| secondary | ABCDE vs runbook, named held-out or blind | case success | 28 | 20 | 0 | +71 pts [+54 pts to +86 pts] | <0.001 | <0.001 | Exact McNemar; paired bootstrap |
| secondary | ABCDE vs ReAct | case success | 40 | 16 | 0 | +40 pts [+25 pts to +55 pts] | <0.001 | <0.001 | Exact McNemar; paired bootstrap |
| secondary | ABCDE vs naive verification | false all-clear | 40 | 0 | 0 | +0 pts [+0 pts to +0 pts] | 1.000 | 1.000 | Exact McNemar; paired bootstrap |
| secondary | ABCDE vs runbook | user-impact seconds | 40 | unavailable | unavailable | unavailable [unavailable] | 0.098 | 0.197 | Wilcoxon signed-rank |

b: pairs where the endpoint is present for the first-named arm and absent for the second; c: the reverse. For case success, b counts pairs only the first arm succeeded on. For false all-clear (lower is better), b counts pairs where only the first arm made the false claim, so a larger b is worse for the first arm. Difference is first minus second: percentage points for rates, seconds for user impact. Rows without b, c or an interval (such as the Wilcoxon test on user-impact seconds) show unavailable.

## Charts

Dot = estimate; line = 95% interval. The tables below hold every number in the charts. Do not read overlap, or a gap, between intervals as a test.

![Case success by arm with 95% Wilson intervals](case_success.png)

![Mean user-impact seconds by arm with 95% bootstrap intervals](user_impact.png)

![Mean model tokens and cost per case by arm with 95% bootstrap intervals](tokens_cost.png)

## Results by arm (all valid cases)

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 39/40 | 98% | 87%–100% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 19/40 | 48% | 33%–63% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 23/40 | 57% | 42%–71% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 33/40 | 82% | 68%–91% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 40/40 | 100% | 91%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 4/40 | 10% | 4%–23% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 36/40 | 90% | 77%–96% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 32/32 | 100% | 89%–100% |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 11/32 | 34% | 20%–52% |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 26/32 | 81% | 65%–91% |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 31/32 | 97% | 84%–99% |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 32/32 | 100% | 89%–100% |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/32 | 0% | 0%–11% |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 32/32 | 100% | 89%–100% |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/35 | 0% | 0%–10% |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 1/16 | 6% | 1%–28% |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/23 | 0% | 0%–14% |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/29 | 0% | 0%–12% |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/36 | 0% | 0%–10% |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 36/40 | 90% | 77%–96% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/36 | 0% | 0%–10% |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 1/36 | 3% | 0%–14% |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 20/36 | 56% | 40%–70% |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 6/36 | 17% | 8%–32% |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 7/36 | 19% | 10%–35% |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/36 | 0% | 0%–10% |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/36 | 0% | 0%–10% |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/36 | 0% | 0%–10% |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/40 | 0% | 0%–9% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/40 | 0% | 0%–9% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/40 | 0% | 0%–9% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/40 | 0% | 0%–9% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/40 | 0% | 0%–9% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/40 | 0% | 0%–9% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/40 | 0% | 0%–9% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 30/40 | 75% | 60%–86% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 30/40 | 75% | 60%–86% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 30/40 | 75% | 60%–86% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 30/40 | 75% | 60%–86% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 30/40 | 75% | 60%–86% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 32/40 | 80% | 65%–90% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 22/40 | 55% | 40%–69% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/4 | 0% | 0%–49% |
| Correct escalation | ABCDE agent | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/4 | 0% | 0%–49% |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 73/73 | 100% | 95%–100% |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 50/51 | 98% | 90%–100% |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 58/59 | 98% | 91%–100% |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 73/74 | 99% | 93%–100% |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 73/73 | 100% | 95%–100% |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 73/73 | 100% | 95%–100% |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 73/73 | 100% | 95%–100% |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 50/73 | 68% | 57%–78% |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 58/73 | 79% | 69%–87% |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 73/73 | 100% | 95%–100% |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 73/73 | 100% | 95%–100% |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/73 | 0% | 0%–5% |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 73/73 | 100% | 95%–100% |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/85 | 0% | 0%–4% |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/60 | 0% | 0%–6% |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/70 | 0% | 0%–5% |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/83 | 0% | 0%–4% |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/86 | 0% | 0%–4% |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/80 | 0% | 0%–5% |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/40 | 0% | 0%–9% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 8/40 | 20% | 10%–35% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 2/40 | 5% | 1%–17% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/40 | 0% | 0%–9% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/40 | 0% | 0%–9% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 27/40 | 68% | 52%–80% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/40 | 0% | 0%–9% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 40 | 19.1 s | 14.2 s–24.0 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 40 | 39.2 s | 24.5 s–55.1 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 40 | 23.6 s | 16.0 s–32.9 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 40 | 18.8 s | 14.1 s–23.4 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 40 | 19.4 s | 14.5 s–24.4 s |
| User-impact seconds (lower is better) | No-op (reference) | 40 | 84.1 s | 65.5 s–102.4 s |
| User-impact seconds (lower is better) | Oracle (reference) | 40 | 10.5 s | 8.1 s–12.8 s |
| Time to mitigate (lower is better) | ABCDE agent | 40 | 19.6 s; censored 0/40 (0%; Wilson 95% 0%–9%) | 14.8 s–24.5 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 40 | 39.2 s; censored 8/40 (20%; Wilson 95% 10%–35%) | 24.8 s–54.8 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 40 | 23.6 s; censored 2/40 (5%; Wilson 95% 1%–17%) | 16.1 s–32.7 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 40 | 19.0 s; censored 0/40 (0%; Wilson 95% 0%–9%) | 14.4 s–23.6 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 40 | 19.5 s; censored 0/40 (0%; Wilson 95% 0%–9%) | 14.6 s–24.5 s |
| Time to mitigate (lower is better) | No-op (reference) | 40 | 82.8 s; censored 27/40 (68%; Wilson 95% 52%–80%) | 64.4 s–101.0 s |
| Time to mitigate (lower is better) | Oracle (reference) | 40 | 10.6 s; censored 0/40 (0%; Wilson 95% 0%–9%) | 8.2 s–12.9 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 40 | 65.5 | 43.6–89.4 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 40 | 106.7 | 66.5–150.1 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 40 | 89.8 | 48.6–150.1 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 40 | 64.5 | 43.1–87.9 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 40 | 67.3 | 44.9–91.9 |
| Failed user journeys per case (lower is better) | No-op (reference) | 40 | 335.5 | 231.1–449.0 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 40 | 34.5 | 22.7–47.5 |
| Model tokens per case | ABCDE agent | 40 | 6,588 | 5,645–7,581 |
| Model tokens per case | Scripted runbook (no AI) | 40 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 31 | 58,821 | 50,037–68,076 |
| Model tokens per case | Naive verify (ablation) | 40 | 10,156 | 8,312–12,067 |
| Model tokens per case | FIFO order (ablation) | 40 | 6,725 | 5,752–7,753 |
| Model tokens per case | No-op (reference) | 40 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 40 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 40 | 5,320 | 4,552–6,145 |
| Model input tokens per case | Scripted runbook (no AI) | 40 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 31 | 56,444 | 47,882–65,455 |
| Model input tokens per case | Naive verify (ablation) | 40 | 8,135 | 6,695–9,633 |
| Model input tokens per case | FIFO order (ablation) | 40 | 5,431 | 4,622–6,291 |
| Model input tokens per case | No-op (reference) | 40 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 40 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 40 | 1,269 | 1,080–1,457 |
| Model output tokens per case | Scripted runbook (no AI) | 40 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 31 | 2,377 | 2,101–2,669 |
| Model output tokens per case | Naive verify (ablation) | 40 | 2,021 | 1,606–2,450 |
| Model output tokens per case | FIFO order (ablation) | 40 | 1,295 | 1,108–1,485 |
| Model output tokens per case | No-op (reference) | 40 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 40 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 40 | $0.0467 | $0.0400–$0.0535 |
| Model cost per case (USD) | Scripted runbook (no AI) | 40 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 31 | $0.2733 | $0.2342–$0.3147 |
| Model cost per case (USD) | Naive verify (ablation) | 40 | $0.0730 | $0.0591–$0.0874 |
| Model cost per case (USD) | FIFO order (ablation) | 40 | $0.0476 | $0.0408–$0.0546 |
| Model cost per case (USD) | No-op (reference) | 40 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 40 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 40 | 2.1 | 1.9–2.2 |
| Model calls per case | Scripted runbook (no AI) | 40 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 40 | 8.8 | 7.8–9.8 |
| Model calls per case | Naive verify (ablation) | 40 | 2.8 | 2.4–3.1 |
| Model calls per case | FIFO order (ablation) | 40 | 2.1 | 1.9–2.3 |
| Model calls per case | No-op (reference) | 40 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 40 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 36 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Scripted runbook (no AI) | 36 | 0.75 | 0.64–0.84 |
| Root-cause F1 | ReAct (free-form agent) | 36 | 0.80 | 0.67–0.92 |
| Root-cause F1 | Naive verify (ablation) | 36 | 0.99 | 0.98–1.00 |
| Root-cause F1 | FIFO order (ablation) | 36 | 1.00 | 1.00–1.00 |
| Root-cause F1 | No-op (reference) | 36 | 0.00 | 0.00–0.00 |
| Root-cause F1 | Oracle (reference) | 36 | 1.00 | 1.00–1.00 |
| Successful actions per case | ABCDE agent | 40 | 2.1 | 1.7–2.5 |
| Successful actions per case | Scripted runbook (no AI) | 40 | 1.2 | 0.9–1.5 |
| Successful actions per case | ReAct (free-form agent) | 40 | 1.7 | 1.3–2.1 |
| Successful actions per case | Naive verify (ablation) | 40 | 2.0 | 1.6–2.5 |
| Successful actions per case | FIFO order (ablation) | 40 | 2.1 | 1.7–2.5 |
| Successful actions per case | No-op (reference) | 40 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 40 | 2.0 | 1.6–2.4 |
| Wasted actions per case (lower is better) | ABCDE agent | 40 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 40 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 40 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 40 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 40 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 40 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 40 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 40 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 40 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 40 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 40 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 40 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 40 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 40 | 0.0 | 0.0–0.0 |

## Results by stratum (descriptive)

Strata are small, so their intervals are wide. They describe where each arm did well or badly; they are not tests.

### Healthy cases (no fault)

Cases: ABCDE agent n = 4, Scripted runbook (no AI) n = 4, ReAct (free-form agent) n = 4, Naive verify (ablation) n = 4, FIFO order (ablation) n = 4, No-op (reference) n = 4, Oracle (reference) n = 4.

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 0/4 | 0% | 0%–49% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 0/4 | 0% | 0%–49% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/4 | 0% | 0%–49% |
| Correct escalation | ABCDE agent | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 0/0 (not estimable) | — | — |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 0/0 (not estimable) | — | — |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 0/0 (not estimable) | — | — |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 0/0 (not estimable) | — | — |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 0/0 (not estimable) | — | — |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/0 (not estimable) | — | — |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | No-op (reference) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | Oracle (reference) | 4 | 0.0 s | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | ABCDE agent | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | No-op (reference) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | Oracle (reference) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Model tokens per case | ABCDE agent | 4 | 912 | 885–932 |
| Model tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 4 | 28,429 | 26,705–31,270 |
| Model tokens per case | Naive verify (ablation) | 4 | 921 | 886–945 |
| Model tokens per case | FIFO order (ablation) | 4 | 922 | 897–942 |
| Model tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 4 | 675 | 649–690 |
| Model input tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 4 | 26,856 | 25,190–29,547 |
| Model input tokens per case | Naive verify (ablation) | 4 | 675 | 649–690 |
| Model input tokens per case | FIFO order (ablation) | 4 | 675 | 649–690 |
| Model input tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 4 | 237 | 232–243 |
| Model output tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 4 | 1,573 | 1,458–1,723 |
| Model output tokens per case | Naive verify (ablation) | 4 | 246 | 235–257 |
| Model output tokens per case | FIFO order (ablation) | 4 | 246 | 237–254 |
| Model output tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 4 | $0.0074 | $0.0073–$0.0076 |
| Model cost per case (USD) | Scripted runbook (no AI) | 4 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 4 | $0.1389 | $0.1311–$0.1527 |
| Model cost per case (USD) | Naive verify (ablation) | 4 | $0.0076 | $0.0073–$0.0079 |
| Model cost per case (USD) | FIFO order (ablation) | 4 | $0.0076 | $0.0074–$0.0078 |
| Model cost per case (USD) | No-op (reference) | 4 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 4 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 4 | 1.0 | 1.0–1.0 |
| Model calls per case | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 4 | 6.2 | 6.0–6.8 |
| Model calls per case | Naive verify (ablation) | 4 | 1.0 | 1.0–1.0 |
| Model calls per case | FIFO order (ablation) | 4 | 1.0 | 1.0–1.0 |
| Model calls per case | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 0 | unavailable | unavailable |
| Root-cause F1 | Scripted runbook (no AI) | 0 | unavailable | unavailable |
| Root-cause F1 | ReAct (free-form agent) | 0 | unavailable | unavailable |
| Root-cause F1 | Naive verify (ablation) | 0 | unavailable | unavailable |
| Root-cause F1 | FIFO order (ablation) | 0 | unavailable | unavailable |
| Root-cause F1 | No-op (reference) | 0 | unavailable | unavailable |
| Root-cause F1 | Oracle (reference) | 0 | unavailable | unavailable |
| Successful actions per case | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |

### Must-escalate cases

Cases: ABCDE agent n = 4, Scripted runbook (no AI) n = 4, ReAct (free-form agent) n = 4, Naive verify (ablation) n = 4, FIFO order (ablation) n = 4, No-op (reference) n = 4, Oracle (reference) n = 4.

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 0/4 | 0% | 0%–49% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 0/0 (not estimable) | — | — |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/0 (not estimable) | — | — |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 0/0 (not estimable) | — | — |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/0 (not estimable) | — | — |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/0 (not estimable) | — | — |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/0 (not estimable) | — | — |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 4/4 | 100% | 51%–100% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/0 (not estimable) | — | — |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 0/0 (not estimable) | — | — |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 0/0 (not estimable) | — | — |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 0/0 (not estimable) | — | — |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 0/0 (not estimable) | — | — |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/0 (not estimable) | — | — |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/0 (not estimable) | — | — |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/0 (not estimable) | — | — |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| Correct escalation | ABCDE agent | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/4 | 0% | 0%–49% |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 4/4 | 100% | 51%–100% |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 4/4 | 100% | 51%–100% |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 4/4 | 100% | 51%–100% |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 4/4 | 100% | 51%–100% |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 4/4 | 100% | 51%–100% |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 4/4 | 100% | 51%–100% |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 4/4 | 100% | 51%–100% |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 4/4 | 100% | 51%–100% |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 4/4 | 100% | 51%–100% |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 4/4 | 100% | 51%–100% |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 4/4 | 100% | 51%–100% |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/4 | 0% | 0%–49% |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 4/4 | 100% | 51%–100% |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | No-op (reference) | 4 | 0.0 s | 0.0 s–0.0 s |
| User-impact seconds (lower is better) | Oracle (reference) | 4 | 0.0 s | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | ABCDE agent | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | No-op (reference) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Time to mitigate (lower is better) | Oracle (reference) | 4 | 0.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 0.0 s–0.0 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Model tokens per case | ABCDE agent | 4 | 5,248 | 5,193–5,311 |
| Model tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 2 | 50,058 | 48,098–52,019 |
| Model tokens per case | Naive verify (ablation) | 4 | 5,264 | 5,130–5,382 |
| Model tokens per case | FIFO order (ablation) | 4 | 5,330 | 5,252–5,409 |
| Model tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 4 | 4,503 | 4,460–4,547 |
| Model input tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 2 | 46,792 | 44,783–48,802 |
| Model input tokens per case | Naive verify (ablation) | 4 | 4,509 | 4,434–4,570 |
| Model input tokens per case | FIFO order (ablation) | 4 | 4,523 | 4,450–4,572 |
| Model input tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 4 | 745 | 683–806 |
| Model output tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 2 | 3,266 | 3,217–3,315 |
| Model output tokens per case | Naive verify (ablation) | 4 | 755 | 673–836 |
| Model output tokens per case | FIFO order (ablation) | 4 | 808 | 768–846 |
| Model output tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 4 | $0.0329 | $0.0317–$0.0341 |
| Model cost per case (USD) | Scripted runbook (no AI) | 4 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 2 | $0.2525 | $0.2454–$0.2595 |
| Model cost per case (USD) | Naive verify (ablation) | 4 | $0.0331 | $0.0314–$0.0349 |
| Model cost per case (USD) | FIFO order (ablation) | 4 | $0.0342 | $0.0333–$0.0352 |
| Model cost per case (USD) | No-op (reference) | 4 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 4 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 4 | 2.0 | 2.0–2.0 |
| Model calls per case | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 4 | 9.0 | 9.0–9.0 |
| Model calls per case | Naive verify (ablation) | 4 | 2.0 | 2.0–2.0 |
| Model calls per case | FIFO order (ablation) | 4 | 2.0 | 2.0–2.0 |
| Model calls per case | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Scripted runbook (no AI) | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | ReAct (free-form agent) | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Naive verify (ablation) | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | FIFO order (ablation) | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | No-op (reference) | 4 | 0.00 | 0.00–0.00 |
| Root-cause F1 | Oracle (reference) | 4 | 1.00 | 1.00–1.00 |
| Successful actions per case | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |

### Practice fault types only (no named held-out or blind fault)

Cases: ABCDE agent n = 4, Scripted runbook (no AI) n = 4, ReAct (free-form agent) n = 4, Naive verify (ablation) n = 4, FIFO order (ablation) n = 4, No-op (reference) n = 4, Oracle (reference) n = 4.

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 0/4 | 0% | 0%–49% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 4/4 | 100% | 51%–100% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 4/4 | 100% | 51%–100% |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 4/4 | 100% | 51%–100% |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 4/4 | 100% | 51%–100% |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 4/4 | 100% | 51%–100% |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 4/4 | 100% | 51%–100% |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/4 | 0% | 0%–49% |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 4/4 | 100% | 51%–100% |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 4/4 | 100% | 51%–100% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/4 | 0% | 0%–49% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 4/4 | 100% | 51%–100% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| Correct escalation | ABCDE agent | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/10 | 90% | 60%–98% |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/9 | 0% | 0%–30% |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/10 | 0% | 0%–28% |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/10 | 0% | 0%–28% |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/9 | 0% | 0%–30% |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/10 | 0% | 0%–28% |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/10 | 0% | 0%–28% |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/9 | 0% | 0%–30% |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 4/4 | 100% | 51%–100% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/4 | 0% | 0%–49% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 4 | 30.0 s | 18.8 s–43.8 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 4 | 20.0 s | 16.2 s–23.8 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 4 | 26.2 s | 21.2 s–32.5 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 4 | 30.0 s | 18.8 s–41.2 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 4 | 31.2 s | 18.8 s–45.0 s |
| User-impact seconds (lower is better) | No-op (reference) | 4 | 125.0 s | 125.0 s–125.0 s |
| User-impact seconds (lower is better) | Oracle (reference) | 4 | 16.2 s | 15.0 s–18.8 s |
| Time to mitigate (lower is better) | ABCDE agent | 4 | 30.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 18.8 s–43.8 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 4 | 20.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 16.2 s–23.8 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 4 | 26.2 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 21.2 s–32.5 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 4 | 30.0 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 18.8 s–41.2 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 4 | 31.2 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 18.8 s–45.0 s |
| Time to mitigate (lower is better) | No-op (reference) | 4 | 122.5 s; censored 4/4 (100%; Wilson 95% 51%–100%) | 122.0 s–123.0 s |
| Time to mitigate (lower is better) | Oracle (reference) | 4 | 16.2 s; censored 0/4 (0%; Wilson 95% 0%–49%) | 15.0 s–18.8 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 4 | 137.8 | 43.5–232.0 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 4 | 76.0 | 33.5–118.5 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 4 | 122.2 | 50.0–194.5 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 4 | 140.8 | 51.5–230.0 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 4 | 149.5 | 51.5–247.5 |
| Failed user journeys per case (lower is better) | No-op (reference) | 4 | 697.5 | 332.0–1,063.0 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 4 | 76.8 | 26.5–127.0 |
| Model tokens per case | ABCDE agent | 4 | 7,761 | 6,192–10,613 |
| Model tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 4 | 52,208 | 41,468–67,720 |
| Model tokens per case | Naive verify (ablation) | 4 | 12,158 | 7,845–16,869 |
| Model tokens per case | FIFO order (ablation) | 4 | 10,325 | 7,692–12,026 |
| Model tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 4 | 6,296 | 4,972–8,770 |
| Model input tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 4 | 50,188 | 39,520–65,410 |
| Model input tokens per case | Naive verify (ablation) | 4 | 9,918 | 6,308–13,735 |
| Model input tokens per case | FIFO order (ablation) | 4 | 8,563 | 6,227–9,909 |
| Model input tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 4 | 1,466 | 1,194–1,846 |
| Model output tokens per case | Scripted runbook (no AI) | 4 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 4 | 2,019 | 1,759–2,364 |
| Model output tokens per case | Naive verify (ablation) | 4 | 2,239 | 1,510–3,134 |
| Model output tokens per case | FIFO order (ablation) | 4 | 1,762 | 1,466–2,117 |
| Model output tokens per case | No-op (reference) | 4 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 4 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 4 | $0.0545 | $0.0439–$0.0719 |
| Model cost per case (USD) | Scripted runbook (no AI) | 4 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 4 | $0.2411 | $0.1970–$0.3078 |
| Model cost per case (USD) | Naive verify (ablation) | 4 | $0.0845 | $0.0560–$0.1176 |
| Model cost per case (USD) | FIFO order (ablation) | 4 | $0.0695 | $0.0542–$0.0820 |
| Model cost per case (USD) | No-op (reference) | 4 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 4 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 4 | 2.2 | 2.0–2.8 |
| Model calls per case | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 4 | 9.0 | 8.0–10.2 |
| Model calls per case | Naive verify (ablation) | 4 | 3.0 | 2.2–3.8 |
| Model calls per case | FIFO order (ablation) | 4 | 2.8 | 2.2–3.0 |
| Model calls per case | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Scripted runbook (no AI) | 4 | 0.95 | 0.85–1.00 |
| Root-cause F1 | ReAct (free-form agent) | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Naive verify (ablation) | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | FIFO order (ablation) | 4 | 1.00 | 1.00–1.00 |
| Root-cause F1 | No-op (reference) | 4 | 0.00 | 0.00–0.00 |
| Root-cause F1 | Oracle (reference) | 4 | 1.00 | 1.00–1.00 |
| Successful actions per case | ABCDE agent | 4 | 2.5 | 2.0–3.0 |
| Successful actions per case | Scripted runbook (no AI) | 4 | 2.5 | 2.0–3.0 |
| Successful actions per case | ReAct (free-form agent) | 4 | 2.2 | 2.0–2.8 |
| Successful actions per case | Naive verify (ablation) | 4 | 2.5 | 2.0–3.0 |
| Successful actions per case | FIFO order (ablation) | 4 | 2.5 | 2.0–3.0 |
| Successful actions per case | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 4 | 2.2 | 2.0–2.8 |
| Wasted actions per case (lower is better) | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 4 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 4 | 0.0 | 0.0–0.0 |

### Named held-out fault types

Cases: ABCDE agent n = 26, Scripted runbook (no AI) n = 26, ReAct (free-form agent) n = 26, Naive verify (ablation) n = 26, FIFO order (ablation) n = 26, No-op (reference) n = 26, Oracle (reference) n = 26.

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 25/26 | 96% | 81%–99% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 5/26 | 19% | 9%–38% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 13/26 | 50% | 32%–68% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 19/26 | 73% | 54%–86% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 26/26 | 100% | 87%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 0/26 | 0% | 0%–13% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 26/26 | 100% | 87%–100% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 26/26 | 100% | 87%–100% |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 5/26 | 19% | 9%–38% |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 20/26 | 77% | 58%–89% |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 25/26 | 96% | 81%–99% |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 26/26 | 100% | 87%–100% |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/26 | 0% | 0%–13% |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 26/26 | 100% | 87%–100% |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/25 | 0% | 0%–13% |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 1/6 | 17% | 3%–56% |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/13 | 0% | 0%–23% |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/19 | 0% | 0%–17% |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/26 | 0% | 0%–13% |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 26/26 | 100% | 87%–100% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/26 | 0% | 0%–13% |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 1/26 | 4% | 1%–19% |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 20/26 | 77% | 58%–89% |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 6/26 | 23% | 11%–42% |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 7/26 | 27% | 14%–46% |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/26 | 0% | 0%–13% |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/26 | 0% | 0%–13% |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/26 | 0% | 0%–13% |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/26 | 0% | 0%–13% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/26 | 0% | 0%–13% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/26 | 0% | 0%–13% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/26 | 0% | 0%–13% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/26 | 0% | 0%–13% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/26 | 0% | 0%–13% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/26 | 0% | 0%–13% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 16/26 | 62% | 43%–78% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 16/26 | 62% | 43%–78% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 16/26 | 62% | 43%–78% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 16/26 | 62% | 43%–78% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 16/26 | 62% | 43%–78% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 18/26 | 69% | 50%–83% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 8/26 | 31% | 17%–50% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| Correct escalation | ABCDE agent | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 57/57 | 100% | 94%–100% |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 34/34 | 100% | 90%–100% |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 42/43 | 98% | 88%–100% |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 57/58 | 98% | 91%–100% |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 57/57 | 100% | 94%–100% |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 57/57 | 100% | 94%–100% |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 57/57 | 100% | 94%–100% |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 34/57 | 60% | 47%–71% |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 42/57 | 74% | 61%–83% |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 57/57 | 100% | 94%–100% |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 57/57 | 100% | 94%–100% |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/57 | 0% | 0%–6% |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 57/57 | 100% | 94%–100% |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/72 | 0% | 0%–5% |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/47 | 0% | 0%–8% |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/58 | 0% | 0%–6% |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/70 | 0% | 0%–5% |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/73 | 0% | 0%–5% |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/68 | 0% | 0%–5% |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/26 | 0% | 0%–13% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 8/26 | 31% | 17%–50% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 2/26 | 8% | 2%–24% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/26 | 0% | 0%–13% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/26 | 0% | 0%–13% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 21/26 | 81% | 62%–91% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/26 | 0% | 0%–13% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 26 | 23.5 s | 18.1 s–28.7 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 26 | 55.8 s | 35.0 s–77.3 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 26 | 30.6 s | 20.4 s–43.7 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 26 | 22.7 s | 17.5 s–27.7 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 26 | 23.3 s | 17.7 s–28.7 s |
| User-impact seconds (lower is better) | No-op (reference) | 26 | 101.0 s | 81.7 s–115.4 s |
| User-impact seconds (lower is better) | Oracle (reference) | 26 | 12.7 s | 10.0 s–15.0 s |
| Time to mitigate (lower is better) | ABCDE agent | 26 | 23.8 s; censored 0/26 (0%; Wilson 95% 0%–13%) | 18.3 s–29.0 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 26 | 55.5 s; censored 8/26 (31%; Wilson 95% 17%–50%) | 35.2 s–76.6 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 26 | 30.4 s; censored 2/26 (8%; Wilson 95% 2%–24%) | 20.4 s–43.2 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 26 | 22.7 s; censored 0/26 (0%; Wilson 95% 0%–13%) | 17.5 s–27.7 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 26 | 23.3 s; censored 0/26 (0%; Wilson 95% 0%–13%) | 17.7 s–28.7 s |
| Time to mitigate (lower is better) | No-op (reference) | 26 | 99.1 s; censored 21/26 (81%; Wilson 95% 62%–91%) | 80.1 s–113.7 s |
| Time to mitigate (lower is better) | Oracle (reference) | 26 | 12.7 s; censored 0/26 (0%; Wilson 95% 0%–13%) | 10.0 s–15.0 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 26 | 75.9 | 50.8–104.1 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 26 | 148.3 | 92.2–206.5 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 26 | 114.7 | 56.7–206.6 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 26 | 73.8 | 49.3–101.4 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 26 | 76.0 | 50.5–104.2 |
| Failed user journeys per case (lower is better) | No-op (reference) | 26 | 388.7 | 267.1–525.7 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 26 | 38.7 | 25.0–55.0 |
| Model tokens per case | ABCDE agent | 26 | 7,606 | 6,668–8,695 |
| Model tokens per case | Scripted runbook (no AI) | 26 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 19 | 69,786 | 58,990–81,321 |
| Model tokens per case | Naive verify (ablation) | 26 | 12,412 | 10,372–14,511 |
| Model tokens per case | FIFO order (ablation) | 26 | 7,406 | 6,500–8,478 |
| Model tokens per case | No-op (reference) | 26 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 26 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 26 | 6,084 | 5,301–7,004 |
| Model input tokens per case | Scripted runbook (no AI) | 26 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 19 | 67,159 | 56,684–78,356 |
| Model input tokens per case | Naive verify (ablation) | 26 | 9,860 | 8,254–11,483 |
| Model input tokens per case | FIFO order (ablation) | 26 | 5,903 | 5,157–6,808 |
| Model input tokens per case | No-op (reference) | 26 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 26 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 26 | 1,522 | 1,339–1,713 |
| Model output tokens per case | Scripted runbook (no AI) | 26 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 19 | 2,628 | 2,276–2,991 |
| Model output tokens per case | Naive verify (ablation) | 26 | 2,552 | 2,074–3,052 |
| Model output tokens per case | FIFO order (ablation) | 26 | 1,502 | 1,319–1,695 |
| Model output tokens per case | No-op (reference) | 26 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 26 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 26 | $0.0548 | $0.0483–$0.0619 |
| Model cost per case (USD) | Scripted runbook (no AI) | 26 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 19 | $0.3212 | $0.2726–$0.3730 |
| Model cost per case (USD) | Naive verify (ablation) | 26 | $0.0905 | $0.0749–$0.1067 |
| Model cost per case (USD) | FIFO order (ablation) | 26 | $0.0537 | $0.0473–$0.0609 |
| Model cost per case (USD) | No-op (reference) | 26 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 26 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 26 | 2.2 | 2.1–2.4 |
| Model calls per case | Scripted runbook (no AI) | 26 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 26 | 9.2 | 7.7–10.6 |
| Model calls per case | Naive verify (ablation) | 26 | 3.2 | 2.8–3.5 |
| Model calls per case | FIFO order (ablation) | 26 | 2.2 | 2.0–2.4 |
| Model calls per case | No-op (reference) | 26 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 26 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 26 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Scripted runbook (no AI) | 26 | 0.66 | 0.53–0.77 |
| Root-cause F1 | ReAct (free-form agent) | 26 | 0.73 | 0.55–0.88 |
| Root-cause F1 | Naive verify (ablation) | 26 | 0.99 | 0.98–1.00 |
| Root-cause F1 | FIFO order (ablation) | 26 | 1.00 | 1.00–1.00 |
| Root-cause F1 | No-op (reference) | 26 | 0.00 | 0.00–0.00 |
| Root-cause F1 | Oracle (reference) | 26 | 1.00 | 1.00–1.00 |
| Successful actions per case | ABCDE agent | 26 | 2.7 | 2.4–3.1 |
| Successful actions per case | Scripted runbook (no AI) | 26 | 1.3 | 1.0–1.6 |
| Successful actions per case | ReAct (free-form agent) | 26 | 2.2 | 1.7–2.7 |
| Successful actions per case | Naive verify (ablation) | 26 | 2.7 | 2.3–3.0 |
| Successful actions per case | FIFO order (ablation) | 26 | 2.7 | 2.4–3.1 |
| Successful actions per case | No-op (reference) | 26 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 26 | 2.6 | 2.3–2.9 |
| Wasted actions per case (lower is better) | ABCDE agent | 26 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 26 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 26 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 26 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 26 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 26 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 26 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 26 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 26 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 26 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 26 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 26 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 26 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 26 | 0.0 | 0.0–0.0 |

### Blind fault type

Cases: ABCDE agent n = 5, Scripted runbook (no AI) n = 5, ReAct (free-form agent) n = 5, Naive verify (ablation) n = 5, FIFO order (ablation) n = 5, No-op (reference) n = 5, Oracle (reference) n = 5.

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 5/5 | 100% | 57%–100% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 2/5 | 40% | 12%–77% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 3/5 | 60% | 23%–88% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 3/5 | 60% | 23%–88% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 5/5 | 100% | 57%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 0/5 | 0% | 0%–43% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 5/5 | 100% | 57%–100% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 5/5 | 100% | 57%–100% |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 2/5 | 40% | 12%–77% |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 4/5 | 80% | 38%–96% |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 4/5 | 80% | 38%–96% |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 5/5 | 100% | 57%–100% |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/5 | 0% | 0%–43% |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 5/5 | 100% | 57%–100% |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/5 | 0% | 0%–43% |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 0/2 | 0% | 0%–66% |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/3 | 0% | 0%–56% |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/3 | 0% | 0%–56% |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/5 | 0% | 0%–43% |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 5/5 | 100% | 57%–100% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/5 | 0% | 0%–43% |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 0/5 | 0% | 0%–43% |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 3/5 | 60% | 23%–88% |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 1/5 | 20% | 4%–62% |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 2/5 | 40% | 12%–77% |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/5 | 0% | 0%–43% |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/5 | 0% | 0%–43% |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/5 | 0% | 0%–43% |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/5 | 0% | 0%–43% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/5 | 0% | 0%–43% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/5 | 0% | 0%–43% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/5 | 0% | 0%–43% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/5 | 0% | 0%–43% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/5 | 0% | 0%–43% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/5 | 0% | 0%–43% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 4/5 | 80% | 38%–96% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 4/5 | 80% | 38%–96% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 4/5 | 80% | 38%–96% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 4/5 | 80% | 38%–96% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 4/5 | 80% | 38%–96% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 5/5 | 100% | 57%–100% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 3/5 | 60% | 23%–88% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| Correct escalation | ABCDE agent | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 11/11 | 100% | 74%–100% |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 8/8 | 100% | 68%–100% |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 11/11 | 100% | 74%–100% |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 11/11 | 100% | 74%–100% |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 11/11 | 100% | 74%–100% |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 11/11 | 100% | 74%–100% |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 8/11 | 73% | 43%–90% |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 9/11 | 82% | 52%–95% |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 11/11 | 100% | 74%–100% |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 11/11 | 100% | 74%–100% |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/11 | 0% | 0%–26% |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 11/11 | 100% | 74%–100% |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/13 | 0% | 0%–23% |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/10 | 0% | 0%–28% |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/12 | 0% | 0%–24% |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/12 | 0% | 0%–24% |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/15 | 0% | 0%–20% |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/13 | 0% | 0%–23% |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/5 | 0% | 0%–43% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 0/5 | 0% | 0%–43% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 0/5 | 0% | 0%–43% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/5 | 0% | 0%–43% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/5 | 0% | 0%–43% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 5/5 | 100% | 57%–100% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/5 | 0% | 0%–43% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 5 | 30.0 s | 20.0 s–41.0 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 5 | 22.0 s | 18.0 s–25.0 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 5 | 31.0 s | 23.0 s–39.0 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 5 | 30.0 s | 22.0 s–38.0 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 5 | 31.0 s | 21.0 s–41.0 s |
| User-impact seconds (lower is better) | No-op (reference) | 5 | 123.0 s | 121.0 s–125.0 s |
| User-impact seconds (lower is better) | Oracle (reference) | 5 | 14.0 s | 11.0 s–17.0 s |
| Time to mitigate (lower is better) | ABCDE agent | 5 | 32.0 s; censored 0/5 (0%; Wilson 95% 0%–43%) | 24.0 s–41.0 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 5 | 23.0 s; censored 0/5 (0%; Wilson 95% 0%–43%) | 21.0 s–25.0 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 5 | 32.0 s; censored 0/5 (0%; Wilson 95% 0%–43%) | 25.0 s–40.0 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 5 | 32.0 s; censored 0/5 (0%; Wilson 95% 0%–43%) | 26.0 s–39.0 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 5 | 32.0 s; censored 0/5 (0%; Wilson 95% 0%–43%) | 24.0 s–41.0 s |
| Time to mitigate (lower is better) | No-op (reference) | 5 | 123.1 s; censored 5/5 (100%; Wilson 95% 57%–100%) | 122.5 s–123.7 s |
| Time to mitigate (lower is better) | Oracle (reference) | 5 | 15.0 s; censored 0/5 (0%; Wilson 95% 0%–43%) | 12.0 s–18.0 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 5 | 65.2 | 49.0–89.2 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 5 | 45.0 | 30.2–63.2 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 5 | 67.0 | 48.0–85.0 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 5 | 61.6 | 50.0–75.8 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 5 | 69.4 | 48.4–93.2 |
| Failed user journeys per case (lower is better) | No-op (reference) | 5 | 257.6 | 254.0–262.0 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 5 | 28.2 | 23.0–34.8 |
| Model tokens per case | ABCDE agent | 5 | 7,586 | 5,153–11,797 |
| Model tokens per case | Scripted runbook (no AI) | 5 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 4 | 68,521 | 37,430–105,908 |
| Model tokens per case | Naive verify (ablation) | 5 | 7,865 | 5,205–12,250 |
| Model tokens per case | FIFO order (ablation) | 5 | 8,668 | 5,229–12,920 |
| Model tokens per case | No-op (reference) | 5 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 5 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 5 | 6,324 | 4,376–9,873 |
| Model input tokens per case | Scripted runbook (no AI) | 5 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 4 | 66,065 | 35,990–102,270 |
| Model input tokens per case | Naive verify (ablation) | 5 | 6,335 | 4,349–9,925 |
| Model input tokens per case | FIFO order (ablation) | 5 | 7,151 | 4,421–10,674 |
| Model input tokens per case | No-op (reference) | 5 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 5 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 5 | 1,263 | 756–1,946 |
| Model output tokens per case | Scripted runbook (no AI) | 5 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 4 | 2,456 | 1,440–3,638 |
| Model output tokens per case | Naive verify (ablation) | 5 | 1,530 | 817–2,365 |
| Model output tokens per case | FIFO order (ablation) | 5 | 1,517 | 808–2,246 |
| Model output tokens per case | No-op (reference) | 5 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 5 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 5 | $0.0506 | $0.0328–$0.0783 |
| Model cost per case (USD) | Scripted runbook (no AI) | 5 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 4 | $0.3134 | $0.1728–$0.4818 |
| Model cost per case (USD) | Naive verify (ablation) | 5 | $0.0559 | $0.0339–$0.0868 |
| Model cost per case (USD) | FIFO order (ablation) | 5 | $0.0590 | $0.0338–$0.0876 |
| Model cost per case (USD) | No-op (reference) | 5 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 5 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 5 | 2.4 | 2.0–3.2 |
| Model calls per case | Scripted runbook (no AI) | 5 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 5 | 10.0 | 6.4–14.2 |
| Model calls per case | Naive verify (ablation) | 5 | 2.4 | 2.0–3.2 |
| Model calls per case | FIFO order (ablation) | 5 | 2.6 | 2.0–3.4 |
| Model calls per case | No-op (reference) | 5 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 5 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 5 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Scripted runbook (no AI) | 5 | 0.85 | 0.75–0.96 |
| Root-cause F1 | ReAct (free-form agent) | 5 | 0.80 | 0.40–1.00 |
| Root-cause F1 | Naive verify (ablation) | 5 | 1.00 | 1.00–1.00 |
| Root-cause F1 | FIFO order (ablation) | 5 | 1.00 | 1.00–1.00 |
| Root-cause F1 | No-op (reference) | 5 | 0.00 | 0.00–0.00 |
| Root-cause F1 | Oracle (reference) | 5 | 1.00 | 1.00–1.00 |
| Successful actions per case | ABCDE agent | 5 | 2.6 | 1.6–3.4 |
| Successful actions per case | Scripted runbook (no AI) | 5 | 1.6 | 1.2–2.0 |
| Successful actions per case | ReAct (free-form agent) | 5 | 2.2 | 1.2–3.2 |
| Successful actions per case | Naive verify (ablation) | 5 | 2.2 | 1.6–2.8 |
| Successful actions per case | FIFO order (ablation) | 5 | 2.6 | 1.6–3.4 |
| Successful actions per case | No-op (reference) | 5 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 5 | 2.6 | 1.6–3.4 |
| Wasted actions per case (lower is better) | ABCDE agent | 5 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 5 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 5 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 5 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 5 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 5 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 5 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 5 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 5 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 5 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 5 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 5 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 5 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 5 | 0.0 | 0.0–0.0 |

### Single-fault and healthy cases

Cases: ABCDE agent n = 13, Scripted runbook (no AI) n = 13, ReAct (free-form agent) n = 13, Naive verify (ablation) n = 13, FIFO order (ablation) n = 13, No-op (reference) n = 13, Oracle (reference) n = 13.

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 13/13 | 100% | 77%–100% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 10/13 | 77% | 50%–92% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 7/13 | 54% | 29%–77% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 13/13 | 100% | 77%–100% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 13/13 | 100% | 77%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 4/13 | 31% | 13%–58% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 9/13 | 69% | 42%–87% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 5/5 | 100% | 57%–100% |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 2/5 | 40% | 12%–77% |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 4/5 | 80% | 38%–96% |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 5/5 | 100% | 57%–100% |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 5/5 | 100% | 57%–100% |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/5 | 0% | 0%–43% |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 5/5 | 100% | 57%–100% |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/9 | 0% | 0%–30% |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 1/7 | 14% | 3%–51% |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/7 | 0% | 0%–35% |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/9 | 0% | 0%–30% |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/9 | 0% | 0%–30% |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 9/13 | 69% | 42%–87% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/9 | 0% | 0%–30% |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 0/9 | 0% | 0%–30% |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 2/9 | 22% | 6%–55% |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 1/9 | 11% | 2%–43% |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 0/9 | 0% | 0%–30% |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/9 | 0% | 0%–30% |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/9 | 0% | 0%–30% |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/9 | 0% | 0%–30% |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/13 | 0% | 0%–23% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/13 | 0% | 0%–23% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/13 | 0% | 0%–23% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/13 | 0% | 0%–23% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/13 | 0% | 0%–23% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/13 | 0% | 0%–23% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/13 | 0% | 0%–23% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 12/13 | 92% | 67%–99% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 12/13 | 92% | 67%–99% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 12/13 | 92% | 67%–99% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 12/13 | 92% | 67%–99% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 12/13 | 92% | 67%–99% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 12/13 | 92% | 67%–99% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 10/13 | 77% | 50%–92% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/4 | 0% | 0%–49% |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/4 | 0% | 0%–49% |
| Correct escalation | ABCDE agent | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/4 | 0% | 0%–49% |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 4/4 | 100% | 51%–100% |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 6/6 | 100% | 61%–100% |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 8/8 | 100% | 68%–100% |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 9/9 | 100% | 70%–100% |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 6/9 | 67% | 35%–88% |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 8/9 | 89% | 57%–98% |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/9 | 0% | 0%–30% |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 9/9 | 100% | 70%–100% |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/7 | 0% | 0%–35% |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/4 | 0% | 0%–49% |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/5 | 0% | 0%–43% |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/7 | 0% | 0%–35% |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/7 | 0% | 0%–35% |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/7 | 0% | 0%–35% |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/13 | 0% | 0%–23% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 1/13 | 8% | 1%–33% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 0/13 | 0% | 0%–23% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/13 | 0% | 0%–23% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/13 | 0% | 0%–23% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 2/13 | 15% | 4%–42% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/13 | 0% | 0%–23% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 13 | 3.1 s | 0.0 s–7.7 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 13 | 11.2 s | 0.0 s–31.2 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 13 | 3.1 s | 0.0 s–7.7 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 13 | 3.5 s | 0.0 s–8.5 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 13 | 3.1 s | 0.0 s–7.7 s |
| User-impact seconds (lower is better) | No-op (reference) | 13 | 18.8 s | 0.0 s–46.9 s |
| User-impact seconds (lower is better) | Oracle (reference) | 13 | 1.9 s | 0.0 s–4.6 s |
| Time to mitigate (lower is better) | ABCDE agent | 13 | 3.5 s; censored 0/13 (0%; Wilson 95% 0%–23%) | 0.0 s–8.5 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 13 | 12.1 s; censored 1/13 (8%; Wilson 95% 1%–33%) | 0.0 s–32.0 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 13 | 3.5 s; censored 0/13 (0%; Wilson 95% 0%–23%) | 0.0 s–8.5 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 13 | 3.8 s; censored 0/13 (0%; Wilson 95% 0%–23%) | 0.0 s–9.6 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 13 | 3.5 s; censored 0/13 (0%; Wilson 95% 0%–23%) | 0.0 s–8.5 s |
| Time to mitigate (lower is better) | No-op (reference) | 13 | 18.9 s; censored 2/13 (15%; Wilson 95% 4%–42%) | 0.0 s–47.1 s |
| Time to mitigate (lower is better) | Oracle (reference) | 13 | 2.3 s; censored 0/13 (0%; Wilson 95% 0%–23%) | 0.0 s–5.8 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 13 | 6.9 | 0.0–17.2 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 13 | 25.7 | 0.0–74.7 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 13 | 6.8 | 0.0–16.8 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 13 | 7.1 | 0.0–17.6 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 13 | 7.1 | 0.0–17.5 |
| Failed user journeys per case (lower is better) | No-op (reference) | 13 | 43.5 | 0.0–106.9 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 13 | 4.3 | 0.0–10.7 |
| Model tokens per case | ABCDE agent | 13 | 3,939 | 2,847–4,981 |
| Model tokens per case | Scripted runbook (no AI) | 13 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 10 | 38,939 | 30,409–49,916 |
| Model tokens per case | Naive verify (ablation) | 13 | 4,905 | 3,190–6,663 |
| Model tokens per case | FIFO order (ablation) | 13 | 3,973 | 2,880–5,024 |
| Model tokens per case | No-op (reference) | 13 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 13 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 13 | 3,299 | 2,380–4,189 |
| Model input tokens per case | Scripted runbook (no AI) | 13 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 10 | 36,956 | 28,850–47,549 |
| Model input tokens per case | Naive verify (ablation) | 13 | 4,141 | 2,677–5,622 |
| Model input tokens per case | FIFO order (ablation) | 13 | 3,305 | 2,381–4,199 |
| Model input tokens per case | No-op (reference) | 13 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 13 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 13 | 641 | 474–803 |
| Model output tokens per case | Scripted runbook (no AI) | 13 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 10 | 1,983 | 1,545–2,484 |
| Model output tokens per case | Naive verify (ablation) | 13 | 764 | 513–1,054 |
| Model output tokens per case | FIFO order (ablation) | 13 | 668 | 498–829 |
| Model output tokens per case | No-op (reference) | 13 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 13 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 13 | $0.0260 | $0.0188–$0.0327 |
| Model cost per case (USD) | Scripted runbook (no AI) | 13 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 10 | $0.1875 | $0.1468–$0.2377 |
| Model cost per case (USD) | Naive verify (ablation) | 13 | $0.0318 | $0.0209–$0.0434 |
| Model cost per case (USD) | FIFO order (ablation) | 13 | $0.0266 | $0.0194–$0.0332 |
| Model cost per case (USD) | No-op (reference) | 13 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 13 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 13 | 1.7 | 1.5–1.9 |
| Model calls per case | Scripted runbook (no AI) | 13 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 13 | 7.3 | 6.1–8.5 |
| Model calls per case | Naive verify (ablation) | 13 | 1.9 | 1.5–2.3 |
| Model calls per case | FIFO order (ablation) | 13 | 1.7 | 1.5–1.9 |
| Model calls per case | No-op (reference) | 13 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 13 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 9 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Scripted runbook (no AI) | 9 | 0.67 | 0.33–0.89 |
| Root-cause F1 | ReAct (free-form agent) | 9 | 0.89 | 0.67–1.00 |
| Root-cause F1 | Naive verify (ablation) | 9 | 1.00 | 1.00–1.00 |
| Root-cause F1 | FIFO order (ablation) | 9 | 1.00 | 1.00–1.00 |
| Root-cause F1 | No-op (reference) | 9 | 0.00 | 0.00–0.00 |
| Root-cause F1 | Oracle (reference) | 9 | 1.00 | 1.00–1.00 |
| Successful actions per case | ABCDE agent | 13 | 0.5 | 0.2–0.9 |
| Successful actions per case | Scripted runbook (no AI) | 13 | 0.2 | 0.0–0.4 |
| Successful actions per case | ReAct (free-form agent) | 13 | 0.4 | 0.1–0.8 |
| Successful actions per case | Naive verify (ablation) | 13 | 0.5 | 0.2–0.9 |
| Successful actions per case | FIFO order (ablation) | 13 | 0.5 | 0.2–0.9 |
| Successful actions per case | No-op (reference) | 13 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 13 | 0.5 | 0.2–0.9 |
| Wasted actions per case (lower is better) | ABCDE agent | 13 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 13 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 13 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 13 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 13 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 13 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 13 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 13 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 13 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 13 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 13 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 13 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 13 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 13 | 0.0 | 0.0–0.0 |

### Two-fault cases

Cases: ABCDE agent n = 17, Scripted runbook (no AI) n = 17, ReAct (free-form agent) n = 17, Naive verify (ablation) n = 17, FIFO order (ablation) n = 17, No-op (reference) n = 17, Oracle (reference) n = 17.

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 16/17 | 94% | 73%–99% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 7/17 | 41% | 22%–64% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 10/17 | 59% | 36%–78% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 13/17 | 76% | 53%–90% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 17/17 | 100% | 82%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 0/17 | 0% | 0%–18% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 17/17 | 100% | 82%–100% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 17/17 | 100% | 82%–100% |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 7/17 | 41% | 22%–64% |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 13/17 | 76% | 53%–90% |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 17/17 | 100% | 82%–100% |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 17/17 | 100% | 82%–100% |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/17 | 0% | 0%–18% |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 17/17 | 100% | 82%–100% |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/16 | 0% | 0%–19% |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 0/7 | 0% | 0%–35% |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/10 | 0% | 0%–28% |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/13 | 0% | 0%–23% |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/17 | 0% | 0%–18% |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 17/17 | 100% | 82%–100% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/17 | 0% | 0%–18% |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 1/17 | 6% | 1%–27% |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 10/17 | 59% | 36%–78% |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 3/17 | 18% | 6%–41% |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 4/17 | 24% | 10%–47% |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/17 | 0% | 0%–18% |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/17 | 0% | 0%–18% |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/17 | 0% | 0%–18% |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/17 | 0% | 0%–18% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/17 | 0% | 0%–18% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/17 | 0% | 0%–18% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/17 | 0% | 0%–18% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/17 | 0% | 0%–18% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/17 | 0% | 0%–18% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/17 | 0% | 0%–18% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 12/17 | 71% | 47%–87% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 12/17 | 71% | 47%–87% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 12/17 | 71% | 47%–87% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 12/17 | 71% | 47%–87% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 12/17 | 71% | 47%–87% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 13/17 | 76% | 53%–90% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 8/17 | 47% | 26%–69% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| Correct escalation | ABCDE agent | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 34/34 | 100% | 90%–100% |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 23/24 | 96% | 80%–99% |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 26/26 | 100% | 87%–100% |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 34/35 | 97% | 85%–99% |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 34/34 | 100% | 90%–100% |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 34/34 | 100% | 90%–100% |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 34/34 | 100% | 90%–100% |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 23/34 | 68% | 51%–81% |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 26/34 | 76% | 60%–88% |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 34/34 | 100% | 90%–100% |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 34/34 | 100% | 90%–100% |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/34 | 0% | 0%–10% |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 34/34 | 100% | 90%–100% |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/43 | 0% | 0%–8% |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/29 | 0% | 0%–12% |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/30 | 0% | 0%–11% |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/42 | 0% | 0%–8% |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/42 | 0% | 0%–8% |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/39 | 0% | 0%–9% |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/17 | 0% | 0%–18% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 4/17 | 24% | 10%–47% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 2/17 | 12% | 3%–34% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/17 | 0% | 0%–18% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/17 | 0% | 0%–18% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 15/17 | 88% | 66%–97% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/17 | 0% | 0%–18% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 17 | 21.2 s | 16.5 s–25.6 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 17 | 46.8 s | 24.7 s–72.6 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 17 | 33.5 s | 19.7 s–52.1 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 17 | 21.2 s | 16.5 s–25.3 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 17 | 21.2 s | 16.5 s–25.6 s |
| User-impact seconds (lower is better) | No-op (reference) | 17 | 110.0 s | 87.9 s–125.0 s |
| User-impact seconds (lower is better) | Oracle (reference) | 17 | 13.2 s | 10.6 s–15.3 s |
| Time to mitigate (lower is better) | ABCDE agent | 17 | 21.5 s; censored 0/17 (0%; Wilson 95% 0%–18%) | 16.8 s–25.9 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 17 | 46.2 s; censored 4/17 (24%; Wilson 95% 10%–47%) | 24.5 s–71.5 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 17 | 33.3 s; censored 2/17 (12%; Wilson 95% 3%–34%) | 19.7 s–51.3 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 17 | 21.5 s; censored 0/17 (0%; Wilson 95% 0%–18%) | 16.8 s–25.9 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 17 | 21.2 s; censored 0/17 (0%; Wilson 95% 0%–18%) | 16.5 s–25.6 s |
| Time to mitigate (lower is better) | No-op (reference) | 17 | 108.0 s; censored 15/17 (88%; Wilson 95% 66%–97%) | 86.4 s–122.5 s |
| Time to mitigate (lower is better) | Oracle (reference) | 17 | 13.2 s; censored 0/17 (0%; Wilson 95% 0%–18%) | 10.6 s–15.3 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 17 | 75.5 | 47.4–109.1 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 17 | 128.8 | 68.8–197.9 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 17 | 140.1 | 56.5–268.8 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 17 | 74.5 | 46.2–108.9 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 17 | 76.6 | 47.4–112.1 |
| Failed user journeys per case (lower is better) | No-op (reference) | 17 | 425.4 | 279.7–596.1 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 17 | 43.2 | 26.1–63.7 |
| Model tokens per case | ABCDE agent | 17 | 7,264 | 6,332–8,377 |
| Model tokens per case | Scripted runbook (no AI) | 17 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 13 | 56,406 | 48,279–65,777 |
| Model tokens per case | Naive verify (ablation) | 17 | 11,153 | 9,176–13,202 |
| Model tokens per case | FIFO order (ablation) | 17 | 6,865 | 6,205–7,762 |
| Model tokens per case | No-op (reference) | 17 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 17 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 17 | 5,819 | 5,060–6,717 |
| Model input tokens per case | Scripted runbook (no AI) | 17 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 13 | 54,203 | 46,328–63,297 |
| Model input tokens per case | Naive verify (ablation) | 17 | 8,880 | 7,370–10,427 |
| Model input tokens per case | FIFO order (ablation) | 17 | 5,527 | 4,945–6,343 |
| Model input tokens per case | No-op (reference) | 17 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 17 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 17 | 1,446 | 1,238–1,688 |
| Model output tokens per case | Scripted runbook (no AI) | 17 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 13 | 2,203 | 1,924–2,530 |
| Model output tokens per case | Naive verify (ablation) | 17 | 2,273 | 1,787–2,781 |
| Model output tokens per case | FIFO order (ablation) | 17 | 1,338 | 1,214–1,460 |
| Model output tokens per case | No-op (reference) | 17 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 17 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 17 | $0.0522 | $0.0454–$0.0604 |
| Model cost per case (USD) | Scripted runbook (no AI) | 17 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 13 | $0.2609 | $0.2242–$0.3033 |
| Model cost per case (USD) | Naive verify (ablation) | 17 | $0.0810 | $0.0654–$0.0973 |
| Model cost per case (USD) | FIFO order (ablation) | 17 | $0.0489 | $0.0447–$0.0540 |
| Model cost per case (USD) | No-op (reference) | 17 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 17 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 17 | 2.2 | 2.0–2.4 |
| Model calls per case | Scripted runbook (no AI) | 17 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 17 | 7.9 | 6.5–9.2 |
| Model calls per case | Naive verify (ablation) | 17 | 2.9 | 2.6–3.3 |
| Model calls per case | FIFO order (ablation) | 17 | 2.1 | 2.0–2.3 |
| Model calls per case | No-op (reference) | 17 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 17 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 17 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Scripted runbook (no AI) | 17 | 0.75 | 0.63–0.86 |
| Root-cause F1 | ReAct (free-form agent) | 17 | 0.76 | 0.53–0.94 |
| Root-cause F1 | Naive verify (ablation) | 17 | 0.99 | 0.96–1.00 |
| Root-cause F1 | FIFO order (ablation) | 17 | 1.00 | 1.00–1.00 |
| Root-cause F1 | No-op (reference) | 17 | 0.00 | 0.00–0.00 |
| Root-cause F1 | Oracle (reference) | 17 | 1.00 | 1.00–1.00 |
| Successful actions per case | ABCDE agent | 17 | 2.5 | 2.2–2.8 |
| Successful actions per case | Scripted runbook (no AI) | 17 | 1.4 | 1.1–1.8 |
| Successful actions per case | ReAct (free-form agent) | 17 | 1.8 | 1.4–2.1 |
| Successful actions per case | Naive verify (ablation) | 17 | 2.5 | 2.2–2.8 |
| Successful actions per case | FIFO order (ablation) | 17 | 2.5 | 2.2–2.8 |
| Successful actions per case | No-op (reference) | 17 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 17 | 2.3 | 2.1–2.5 |
| Wasted actions per case (lower is better) | ABCDE agent | 17 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 17 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 17 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 17 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 17 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 17 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 17 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 17 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 17 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 17 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 17 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 17 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 17 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 17 | 0.0 | 0.0–0.0 |

### Three-fault cases

Cases: ABCDE agent n = 10, Scripted runbook (no AI) n = 10, ReAct (free-form agent) n = 10, Naive verify (ablation) n = 10, FIFO order (ablation) n = 10, No-op (reference) n = 10, Oracle (reference) n = 10.

**Rates** (n/N, estimate, 95% Wilson interval)

| Metric | Arm | N counts | n/N | Estimate | Wilson 95% |
|---|---|---|---|---|---|
| Case success (primary endpoint) | ABCDE agent | valid cases with an observed success verdict | 10/10 | 100% | 72%–100% |
| Case success (primary endpoint) | Scripted runbook (no AI) | valid cases with an observed success verdict | 2/10 | 20% | 6%–51% |
| Case success (primary endpoint) | ReAct (free-form agent) | valid cases with an observed success verdict | 6/10 | 60% | 31%–83% |
| Case success (primary endpoint) | Naive verify (ablation) | valid cases with an observed success verdict | 7/10 | 70% | 40%–89% |
| Case success (primary endpoint) | FIFO order (ablation) | valid cases with an observed success verdict | 10/10 | 100% | 72%–100% |
| Case success (primary endpoint) | No-op (reference) | valid cases with an observed success verdict | 0/10 | 0% | 0%–28% |
| Case success (primary endpoint) | Oracle (reference) | valid cases with an observed success verdict | 10/10 | 100% | 72%–100% |
| Recovery (checker says recovered) | ABCDE agent | fixable cases with a checker verdict | 10/10 | 100% | 72%–100% |
| Recovery (checker says recovered) | Scripted runbook (no AI) | fixable cases with a checker verdict | 2/10 | 20% | 6%–51% |
| Recovery (checker says recovered) | ReAct (free-form agent) | fixable cases with a checker verdict | 9/10 | 90% | 60%–98% |
| Recovery (checker says recovered) | Naive verify (ablation) | fixable cases with a checker verdict | 9/10 | 90% | 60%–98% |
| Recovery (checker says recovered) | FIFO order (ablation) | fixable cases with a checker verdict | 10/10 | 100% | 72%–100% |
| Recovery (checker says recovered) | No-op (reference) | fixable cases with a checker verdict | 0/10 | 0% | 0%–28% |
| Recovery (checker says recovered) | Oracle (reference) | fixable cases with a checker verdict | 10/10 | 100% | 72%–100% |
| False all-clear (lower is better) | ABCDE agent | all-clear claims with a checker verdict | 0/10 | 0% | 0%–28% |
| False all-clear (lower is better) | Scripted runbook (no AI) | all-clear claims with a checker verdict | 0/2 | 0% | 0%–66% |
| False all-clear (lower is better) | ReAct (free-form agent) | all-clear claims with a checker verdict | 0/6 | 0% | 0%–39% |
| False all-clear (lower is better) | Naive verify (ablation) | all-clear claims with a checker verdict | 0/7 | 0% | 0%–35% |
| False all-clear (lower is better) | FIFO order (ablation) | all-clear claims with a checker verdict | 0/10 | 0% | 0%–28% |
| False all-clear (lower is better) | No-op (reference) | all-clear claims with a checker verdict | 10/10 | 100% | 72%–100% |
| False all-clear (lower is better) | Oracle (reference) | all-clear claims with a checker verdict | 0/10 | 0% | 0%–28% |
| Unnecessary escalation (lower is better) | ABCDE agent | valid fixable or healthy cases | 0/10 | 0% | 0%–28% |
| Unnecessary escalation (lower is better) | Scripted runbook (no AI) | valid fixable or healthy cases | 8/10 | 80% | 49%–94% |
| Unnecessary escalation (lower is better) | ReAct (free-form agent) | valid fixable or healthy cases | 2/10 | 20% | 6%–51% |
| Unnecessary escalation (lower is better) | Naive verify (ablation) | valid fixable or healthy cases | 3/10 | 30% | 11%–60% |
| Unnecessary escalation (lower is better) | FIFO order (ablation) | valid fixable or healthy cases | 0/10 | 0% | 0%–28% |
| Unnecessary escalation (lower is better) | No-op (reference) | valid fixable or healthy cases | 0/10 | 0% | 0%–28% |
| Unnecessary escalation (lower is better) | Oracle (reference) | valid fixable or healthy cases | 0/10 | 0% | 0%–28% |
| Harmful action (lower is better) | ABCDE agent | valid cases with observed harm status | 0/10 | 0% | 0%–28% |
| Harmful action (lower is better) | Scripted runbook (no AI) | valid cases with observed harm status | 0/10 | 0% | 0%–28% |
| Harmful action (lower is better) | ReAct (free-form agent) | valid cases with observed harm status | 0/10 | 0% | 0%–28% |
| Harmful action (lower is better) | Naive verify (ablation) | valid cases with observed harm status | 0/10 | 0% | 0%–28% |
| Harmful action (lower is better) | FIFO order (ablation) | valid cases with observed harm status | 0/10 | 0% | 0%–28% |
| Harmful action (lower is better) | No-op (reference) | valid cases with observed harm status | 0/10 | 0% | 0%–28% |
| Harmful action (lower is better) | Oracle (reference) | valid cases with observed harm status | 0/10 | 0% | 0%–28% |
| Handover complete | ABCDE agent | valid cases with operations handover evidence | 6/10 | 60% | 31%–83% |
| Handover complete | Scripted runbook (no AI) | valid cases with operations handover evidence | 6/10 | 60% | 31%–83% |
| Handover complete | ReAct (free-form agent) | valid cases with operations handover evidence | 6/10 | 60% | 31%–83% |
| Handover complete | Naive verify (ablation) | valid cases with operations handover evidence | 6/10 | 60% | 31%–83% |
| Handover complete | FIFO order (ablation) | valid cases with operations handover evidence | 6/10 | 60% | 31%–83% |
| Handover complete | No-op (reference) | valid cases with operations handover evidence | 7/10 | 70% | 40%–89% |
| Handover complete | Oracle (reference) | valid cases with operations handover evidence | 4/10 | 40% | 17%–69% |
| False diagnosis on healthy cases (lower is better) | ABCDE agent | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Scripted runbook (no AI) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | ReAct (free-form agent) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Naive verify (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | FIFO order (ablation) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | No-op (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| False diagnosis on healthy cases (lower is better) | Oracle (reference) | valid healthy cases | 0/0 (not estimable) | — | — |
| Correct escalation | ABCDE agent | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Scripted runbook (no AI) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | ReAct (free-form agent) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Naive verify (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | FIFO order (ablation) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | No-op (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Correct escalation | Oracle (reference) | valid must-escalate cases | 0/0 (not estimable) | — | — |
| Root-cause precision | ABCDE agent | reported root-cause pairs after acceptable secondary pairs are ignored | 30/30 | 100% | 89%–100% |
| Root-cause precision | Scripted runbook (no AI) | reported root-cause pairs after acceptable secondary pairs are ignored | 21/21 | 100% | 85%–100% |
| Root-cause precision | ReAct (free-form agent) | reported root-cause pairs after acceptable secondary pairs are ignored | 24/25 | 96% | 80%–99% |
| Root-cause precision | Naive verify (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 30/30 | 100% | 89%–100% |
| Root-cause precision | FIFO order (ablation) | reported root-cause pairs after acceptable secondary pairs are ignored | 30/30 | 100% | 89%–100% |
| Root-cause precision | No-op (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 0/0 (not estimable) | — | — |
| Root-cause precision | Oracle (reference) | reported root-cause pairs after acceptable secondary pairs are ignored | 30/30 | 100% | 89%–100% |
| Root-cause recall | ABCDE agent | labelled root-cause pairs | 30/30 | 100% | 89%–100% |
| Root-cause recall | Scripted runbook (no AI) | labelled root-cause pairs | 21/30 | 70% | 52%–83% |
| Root-cause recall | ReAct (free-form agent) | labelled root-cause pairs | 24/30 | 80% | 63%–90% |
| Root-cause recall | Naive verify (ablation) | labelled root-cause pairs | 30/30 | 100% | 89%–100% |
| Root-cause recall | FIFO order (ablation) | labelled root-cause pairs | 30/30 | 100% | 89%–100% |
| Root-cause recall | No-op (reference) | labelled root-cause pairs | 0/30 | 0% | 0%–11% |
| Root-cause recall | Oracle (reference) | labelled root-cause pairs | 30/30 | 100% | 89%–100% |
| Harmful-action attempts (lower is better) | ABCDE agent | guard-audited action attempts | 0/35 | 0% | 0%–10% |
| Harmful-action attempts (lower is better) | Scripted runbook (no AI) | guard-audited action attempts | 0/27 | 0% | 0%–12% |
| Harmful-action attempts (lower is better) | ReAct (free-form agent) | guard-audited action attempts | 0/35 | 0% | 0%–10% |
| Harmful-action attempts (lower is better) | Naive verify (ablation) | guard-audited action attempts | 0/34 | 0% | 0%–10% |
| Harmful-action attempts (lower is better) | FIFO order (ablation) | guard-audited action attempts | 0/37 | 0% | 0%–9% |
| Harmful-action attempts (lower is better) | No-op (reference) | guard-audited action attempts | 0/0 (not estimable) | — | — |
| Harmful-action attempts (lower is better) | Oracle (reference) | guard-audited action attempts | 0/34 | 0% | 0%–10% |
| Mitigation still unresolved at the horizon (lower is better) | ABCDE agent | valid cases with an observed mitigation censoring flag | 0/10 | 0% | 0%–28% |
| Mitigation still unresolved at the horizon (lower is better) | Scripted runbook (no AI) | valid cases with an observed mitigation censoring flag | 3/10 | 30% | 11%–60% |
| Mitigation still unresolved at the horizon (lower is better) | ReAct (free-form agent) | valid cases with an observed mitigation censoring flag | 0/10 | 0% | 0%–28% |
| Mitigation still unresolved at the horizon (lower is better) | Naive verify (ablation) | valid cases with an observed mitigation censoring flag | 0/10 | 0% | 0%–28% |
| Mitigation still unresolved at the horizon (lower is better) | FIFO order (ablation) | valid cases with an observed mitigation censoring flag | 0/10 | 0% | 0%–28% |
| Mitigation still unresolved at the horizon (lower is better) | No-op (reference) | valid cases with an observed mitigation censoring flag | 10/10 | 100% | 72%–100% |
| Mitigation still unresolved at the horizon (lower is better) | Oracle (reference) | valid cases with an observed mitigation censoring flag | 0/10 | 0% | 0%–28% |

**Means** (mean per case, 95% bootstrap interval)

| Metric | Arm | Cases with a value | Mean | Bootstrap 95% |
|---|---|---|---|---|
| User-impact seconds (lower is better) | ABCDE agent | 10 | 36.5 s | 30.5 s–42.5 s |
| User-impact seconds (lower is better) | Scripted runbook (no AI) | 10 | 63.0 s | 32.5 s–94.0 s |
| User-impact seconds (lower is better) | ReAct (free-form agent) | 10 | 33.5 s | 29.0 s–38.0 s |
| User-impact seconds (lower is better) | Naive verify (ablation) | 10 | 34.5 s | 28.5 s–40.0 s |
| User-impact seconds (lower is better) | FIFO order (ablation) | 10 | 37.5 s | 31.0 s–43.5 s |
| User-impact seconds (lower is better) | No-op (reference) | 10 | 125.0 s | 125.0 s–125.0 s |
| User-impact seconds (lower is better) | Oracle (reference) | 10 | 17.0 s | 15.5 s–18.5 s |
| Time to mitigate (lower is better) | ABCDE agent | 10 | 37.5 s; censored 0/10 (0%; Wilson 95% 0%–28%) | 32.5 s–43.0 s |
| Time to mitigate (lower is better) | Scripted runbook (no AI) | 10 | 62.6 s; censored 3/10 (30%; Wilson 95% 11%–60%) | 32.4 s–93.1 s |
| Time to mitigate (lower is better) | ReAct (free-form agent) | 10 | 33.5 s; censored 0/10 (0%; Wilson 95% 0%–28%) | 29.0 s–38.0 s |
| Time to mitigate (lower is better) | Naive verify (ablation) | 10 | 34.5 s; censored 0/10 (0%; Wilson 95% 0%–28%) | 28.5 s–40.0 s |
| Time to mitigate (lower is better) | FIFO order (ablation) | 10 | 37.5 s; censored 0/10 (0%; Wilson 95% 0%–28%) | 31.0 s–43.5 s |
| Time to mitigate (lower is better) | No-op (reference) | 10 | 123.1 s; censored 10/10 (100%; Wilson 95% 72%–100%) | 122.5 s–123.7 s |
| Time to mitigate (lower is better) | Oracle (reference) | 10 | 17.0 s; censored 0/10 (0%; Wilson 95% 0%–28%) | 15.5 s–18.5 s |
| Failed user journeys per case (lower is better) | ABCDE agent | 10 | 124.7 | 77.7–176.7 |
| Failed user journeys per case (lower is better) | Scripted runbook (no AI) | 10 | 174.5 | 93.8–257.3 |
| Failed user journeys per case (lower is better) | ReAct (free-form agent) | 10 | 112.2 | 77.7–150.3 |
| Failed user journeys per case (lower is better) | Naive verify (ablation) | 10 | 122.2 | 78.0–170.9 |
| Failed user journeys per case (lower is better) | FIFO order (ablation) | 10 | 129.8 | 82.8–181.1 |
| Failed user journeys per case (lower is better) | No-op (reference) | 10 | 562.4 | 357.9–790.0 |
| Failed user journeys per case (lower is better) | Oracle (reference) | 10 | 59.0 | 33.4–88.8 |
| Model tokens per case | ABCDE agent | 10 | 8,884 | 7,103–11,059 |
| Model tokens per case | Scripted runbook (no AI) | 10 | 0 | 0–0 |
| Model tokens per case | ReAct (free-form agent) | 8 | 87,599 | 73,937–102,480 |
| Model tokens per case | Naive verify (ablation) | 10 | 15,287 | 11,399–19,016 |
| Model tokens per case | FIFO order (ablation) | 10 | 10,067 | 8,158–12,070 |
| Model tokens per case | No-op (reference) | 10 | 0 | 0–0 |
| Model tokens per case | Oracle (reference) | 10 | 0 | 0–0 |
| Model input tokens per case | ABCDE agent | 10 | 7,099 | 5,414–9,054 |
| Model input tokens per case | Scripted runbook (no AI) | 10 | 0 | 0–0 |
| Model input tokens per case | ReAct (free-form agent) | 8 | 84,446 | 71,103–98,957 |
| Model input tokens per case | Naive verify (ablation) | 10 | 12,059 | 8,897–15,056 |
| Model input tokens per case | FIFO order (ablation) | 10 | 8,030 | 6,361–9,798 |
| Model input tokens per case | No-op (reference) | 10 | 0 | 0–0 |
| Model input tokens per case | Oracle (reference) | 10 | 0 | 0–0 |
| Model output tokens per case | ABCDE agent | 10 | 1,785 | 1,590–2,018 |
| Model output tokens per case | Scripted runbook (no AI) | 10 | 0 | 0–0 |
| Model output tokens per case | ReAct (free-form agent) | 8 | 3,154 | 2,718–3,610 |
| Model output tokens per case | Naive verify (ablation) | 10 | 3,228 | 2,468–4,028 |
| Model output tokens per case | FIFO order (ablation) | 10 | 2,036 | 1,783–2,289 |
| Model output tokens per case | No-op (reference) | 10 | 0 | 0–0 |
| Model output tokens per case | Oracle (reference) | 10 | 0 | 0–0 |
| Model cost per case (USD) | ABCDE agent | 10 | $0.0641 | $0.0543–$0.0762 |
| Model cost per case (USD) | Scripted runbook (no AI) | 10 | $0 | $0–$0 |
| Model cost per case (USD) | ReAct (free-form agent) | 8 | $0.4009 | $0.3395–$0.4664 |
| Model cost per case (USD) | Naive verify (ablation) | 10 | $0.1128 | $0.0852–$0.1399 |
| Model cost per case (USD) | FIFO order (ablation) | 10 | $0.0728 | $0.0613–$0.0847 |
| Model cost per case (USD) | No-op (reference) | 10 | $0 | $0–$0 |
| Model cost per case (USD) | Oracle (reference) | 10 | $0 | $0–$0 |
| Model calls per case | ABCDE agent | 10 | 2.4 | 2.0–2.9 |
| Model calls per case | Scripted runbook (no AI) | 10 | 0.0 | 0.0–0.0 |
| Model calls per case | ReAct (free-form agent) | 10 | 12.1 | 10.8–13.5 |
| Model calls per case | Naive verify (ablation) | 10 | 3.5 | 2.8–4.2 |
| Model calls per case | FIFO order (ablation) | 10 | 2.6 | 2.2–3.0 |
| Model calls per case | No-op (reference) | 10 | 0.0 | 0.0–0.0 |
| Model calls per case | Oracle (reference) | 10 | 0.0 | 0.0–0.0 |
| Root-cause F1 | ABCDE agent | 10 | 1.00 | 1.00–1.00 |
| Root-cause F1 | Scripted runbook (no AI) | 10 | 0.81 | 0.73–0.88 |
| Root-cause F1 | ReAct (free-form agent) | 10 | 0.79 | 0.50–1.00 |
| Root-cause F1 | Naive verify (ablation) | 10 | 1.00 | 1.00–1.00 |
| Root-cause F1 | FIFO order (ablation) | 10 | 1.00 | 1.00–1.00 |
| Root-cause F1 | No-op (reference) | 10 | 0.00 | 0.00–0.00 |
| Root-cause F1 | Oracle (reference) | 10 | 1.00 | 1.00–1.00 |
| Successful actions per case | ABCDE agent | 10 | 3.5 | 3.2–3.8 |
| Successful actions per case | Scripted runbook (no AI) | 10 | 2.1 | 1.8–2.4 |
| Successful actions per case | ReAct (free-form agent) | 10 | 3.4 | 3.1–3.7 |
| Successful actions per case | Naive verify (ablation) | 10 | 3.3 | 2.9–3.7 |
| Successful actions per case | FIFO order (ablation) | 10 | 3.5 | 3.2–3.8 |
| Successful actions per case | No-op (reference) | 10 | 0.0 | 0.0–0.0 |
| Successful actions per case | Oracle (reference) | 10 | 3.4 | 3.1–3.7 |
| Wasted actions per case (lower is better) | ABCDE agent | 10 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Scripted runbook (no AI) | 10 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | ReAct (free-form agent) | 10 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Naive verify (ablation) | 10 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | FIFO order (ablation) | 10 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | No-op (reference) | 10 | 0.0 | 0.0–0.0 |
| Wasted actions per case (lower is better) | Oracle (reference) | 10 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ABCDE agent | 10 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Scripted runbook (no AI) | 10 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | ReAct (free-form agent) | 10 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Naive verify (ablation) | 10 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | FIFO order (ablation) | 10 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | No-op (reference) | 10 | 0.0 | 0.0–0.0 |
| Harmful quarantines per case (lower is better) | Oracle (reference) | 10 | 0.0 | 0.0–0.0 |

## Exclusions

Cases are excluded by a pre-registered, mechanical validity rule, applied without looking at any AI arm.

No exclusions are listed in this summary. That alone does not show every case was valid: see Notes for any validity checks still pending.

## Retries

Two kinds of retry are listed. A harness timeout (`harness_timeout`) or a model-provider error (`api_error`) is re-run once at the end and reported separately; it is never counted as a failure of the system. An ordinary harness error (`harness_error`) is also retried once, but if it errors again it counts as a failure. Until its retry completes it remains unresolved. Listed cases are not validity exclusions.

No cases were retried.

## Notes

- Unknown measurements remain unavailable. Rates use their stated observed denominator; missing values are listed in metrics.json.
- abcde: 40 completed pairs; 0 pending validity; 0 invalid; 0 unresolved infrastructure failures.
- fifo: 40 completed pairs; 0 pending validity; 0 invalid; 0 unresolved infrastructure failures.
- naive_verify: 40 completed pairs; 0 pending validity; 0 invalid; 0 unresolved infrastructure failures.
- noop: 40 completed pairs; 0 pending validity; 0 invalid; 0 unresolved infrastructure failures.
- oracle: 40 completed pairs; 0 pending validity; 0 invalid; 0 unresolved infrastructure failures.
- react: 40 completed pairs; 0 pending validity; 0 invalid; 0 unresolved infrastructure failures.
- runbook: 40 completed pairs; 0 pending validity; 0 invalid; 0 unresolved infrastructure failures.
- This is not a paired robustness run.

## Limits and how to read this report

- The cases run on test systems built for this project. The results say nothing about production readiness and make no regulatory claim.
- Samples are small. An interval about ±20 points wide is normal at n = 20.
- Arms are compared only by paired tests on identical cases. Whether two intervals overlap is not a test, and this report draws no conclusion from it.
- Strata, robustness conditions and every metric other than the pre-registered comparisons are descriptive and are not adjusted for multiple looks.
- "unavailable" means the value was not measured or not supplied; 0 means a measured zero. An arm with no model calls (the runbook) has a measured zero for tokens and cost.
- Wilson and bootstrap intervals treat cases as independent draws.

## Glossary

**Arms**

| Arm | Key | What it is |
|---|---|---|
| ABCDE agent | `abcde` | The full system: fixed ABCDE survey, triage order, sustained verification, SBAR handover. |
| Scripted runbook (no AI) | `runbook` | Scripted runbook with no AI; the baseline the system must beat. |
| ReAct (free-form agent) | `react` | Free-form agent with the same tools and model, no fixed survey or triage order. |
| Naive verify (ablation) | `naive_verify` | The full system, but 'errors stopped' counts as recovered; compared on false all-clears. |
| FIFO order (ablation) | `fifo` | The full system, fixing problems in the order found. |
| No-op (reference) | `noop` | Harness reference: does nothing. Used to check that cases are valid. |
| Oracle (reference) | `oracle` | Harness reference: applies the labelled fixes. Used to check that cases are fixable. |

**Terms**

- *Case success*: fixable case recovered by the checker with outcome `recovered` and no harmful action; must-escalate case escalated to the right component with no harmful action; healthy case left alone with outcome `no_incident` and the checker green.
- *False all-clear*: the arm said `recovered` or `no_incident` but the checker was red.
- *User-impact seconds*: 5-second buckets that missed the SLO between the first fault and the horizon, times 5.
- *Wilson 95%*: an interval for a proportion that stays sensible at small n.
- *Bootstrap 95%*: an interval for a mean from resampling cases.
- *McNemar test*: a paired test that uses only the cases where the two arms disagree.
