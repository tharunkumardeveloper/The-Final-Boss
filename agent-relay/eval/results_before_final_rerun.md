# Relay benchmark

Tenant `pml-bench`: 40 customers, 556 customer turns, 160 questions. Answer models alternate per question (`gemini:gemini-3.5-flash-lite`); for each question every system uses the same model and prompt. Intervals are 95% Wilson.

## Headline

On the 160 questions both systems answered: **Relay 91%** [85%–94%] vs **vector baseline (B1) 50%** [42%–58%].

## Gap decomposition by question type (directional: ~16–18 questions per type, wide intervals)

| Type | n | Relay | B1 vector | Δ |
|---|---|---|---|---|
| belief_time | 18 | 94% [74%–99%] | 39% [20%–61%] | +56 pts |
| completeness | 18 | 100% [82%–100%] | 33% [16%–56%] | +67 pts |
| current | 18 | 100% [82%–100%] | 44% [25%–66%] | +56 pts |
| disagreement | 16 | 100% [81%–100%] | 6% [1%–28%] | +94 pts |
| handoff | 18 | 100% [82%–100%] | 67% [44%–84%] | +33 pts |
| multi_hop | 18 | 100% [82%–100%] | 28% [12%–51%] | +72 pts |
| procedural | 18 | 44% [25%–66%] | 50% [29%–71%] | -6 pts |
| unknown | 18 | 89% [67%–97%] | 89% [67%–97%] | +0 pts |
| world_time | 18 | 89% [67%–97%] | 89% [67%–97%] | +0 pts |

Simple recall (`current`, `handoff`) is where a good vector store should stay competitive; the gap should come from updates over time, disagreement, multi-hop and abstention.

## All systems

| System | What it is | Questions | Accuracy [95% CI] | Evidence recall | Retrieval p50 / p95 ms |
|---|---|---|---|---|---|
| FULL | Relay: graph expansion + two clocks + conflict ranking | 160/160 | 91% [85%–94%] | 96% | 216.2 / 254.1 |
| B1 | Vector store: customer-filtered, top-10, dated, newest first | 160/160 | 50% [42%–58%] | 73% | 45.8 / 53.0 |
| A1 | Relay without the two clocks (history unlabelled) | 63/63 | 71% [59%–81%] | 93% | 214.9 / 257.0 |
| A2 | Relay without multi-hop expansion | 63/63 | 81% [70%–89%] | 82% | 124.4 / 147.9 |
| B0 | B1 without dates or recency ordering | 10/63 | 30% [11%–60%] | 60% | 50.0 / 62.2 |

## Ablations (stratified subset)

| System | n | Accuracy [95% CI] |
|---|---|---|
| FULL | 63 | 90% [81%–96%] |
| A1 | 63 | 71% [59%–81%] |
| A2 | 63 | 81% [70%–89%] |
| B1 | 63 | 51% [39%–63%] |
| B0 | 10 | 30% [11%–60%] |

## Abstention (should-refuse questions)

| System | Precision | Recall | Hallucinated answers | False refusals |
|---|---|---|---|---|
| FULL | 89% | 89% | 2 | 2 |
| B1 | 29% | 89% | 2 | 40 |
| A1 | 78% | 100% | 0 | 2 |
| A2 | 58% | 100% | 0 | 5 |

## Per answer model

| System | gemini:gemini-3.5-flash-lite |
|---|---|
| FULL | 91% [85%–94%] |
| B1 | 50% [42%–58%] |
| A1 | 71% [59%–81%] |
| A2 | 81% [70%–89%] |
| B0 | 30% [11%–60%] |

## Still queued (daily LLM quota)

- B0: 53 questions

Resume: `python -m eval.run_eval --tenant pml-bench --phases ablations`
