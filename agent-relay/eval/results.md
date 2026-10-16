# Relay benchmark

Tenant `pml-bench`: 40 customers, 556 customer turns, 160 questions. Answer models alternate per question (`groq6:qwen/qwen3.8-27b`, `groq7:qwen/qwen3.8-27b`, `groq8:qwen/qwen3.8-27b`, `groq9:qwen/qwen3.8-27b`, `groq10:qwen/qwen3.8-27b`, `groq11:qwen/qwen3.8-27b`); for each question every system uses the same model and prompt. Intervals are 95% Wilson.

## Headline

On the 160 questions both systems answered: **Relay 99%** [97%–100%] vs **vector baseline (B1) 61%** [54%–68%].

## Gap decomposition by question type (directional: ~16–18 questions per type, wide intervals)

| Type | n | Relay | B1 vector | Δ |
|---|---|---|---|---|
| belief_time | 18 | 100% [82%–100%] | 89% [67%–97%] | +11 pts |
| completeness | 18 | 100% [82%–100%] | 44% [25%–66%] | +56 pts |
| current | 18 | 100% [82%–100%] | 72% [49%–88%] | +28 pts |
| disagreement | 16 | 100% [81%–100%] | 6% [1%–28%] | +94 pts |
| handoff | 18 | 100% [82%–100%] | 83% [61%–94%] | +17 pts |
| multi_hop | 18 | 100% [82%–100%] | 22% [9%–45%] | +78 pts |
| procedural | 18 | 100% [82%–100%] | 50% [29%–71%] | +50 pts |
| unknown | 18 | 94% [74%–99%] | 78% [55%–91%] | +17 pts |
| world_time | 18 | 100% [82%–100%] | 100% [82%–100%] | +0 pts |

Simple recall (`current`, `handoff`) is where a good vector store should stay competitive; the gap should come from updates over time, disagreement, multi-hop and abstention.

## All systems

| System | What it is | Questions | Accuracy [95% CI] | Evidence recall | Retrieval p50 / p95 ms |
|---|---|---|---|---|---|
| FULL | Relay: graph expansion + two clocks + conflict ranking | 160/160 | 99% [97%–100%] | 100% | 165.8 / 209.8 |
| B1 | Vector store: customer-filtered, top-10, dated, newest first | 160/160 | 61% [54%–68%] | 72% | 45.8 / 57.9 |

## Abstention (should-refuse questions)

| System | Precision | Recall | Hallucinated answers | False refusals |
|---|---|---|---|---|
| B1 | 50% | 78% | 4 | 14 |
| FULL | 100% | 94% | 1 | 0 |

## Per answer model

| System | groq6:qwen/qwen3.8-27b | groq7:qwen/qwen3.8-27b | groq8:qwen/qwen3.8-27b | groq9:qwen/qwen3.8-27b | groq10:qwen/qwen3.8-27b | groq11:qwen/qwen3.8-27b |
|---|---|---|---|---|---|---|
| B1 | 59% [41%–75%] | 59% [41%–75%] | 56% [37%–72%] | 56% [37%–72%] | 73% [54%–86%] | 65% [46%–81%] |
| FULL | 100% [88%–100%] | 100% [88%–100%] | 96% [82%–99%] | 100% [88%–100%] | 100% [87%–100%] | 100% [87%–100%] |

## Out-of-distribution extraction

Customer messages written by a different model (allam-2-7b) in its own style, for 72 planted facts. Extraction recall: **83%** [73%–90%]; predicate accuracy where the value was found: 87%. In-distribution recall for comparison: -.

## External check: LoCoMo

Conversation `conv-26` (174 turns from 8 sessions), 60 of its own questions whose evidence lies in the ingested sessions. Relay used a general personal-life predicate registry. Metric: token F1 (LoCoMo's standard) and refusal accuracy on adversarial questions. License: CC BY-NC 4.0 (snap-research/locomo); downloaded at run time, not redistributed.

| System | n | Mean F1 | F1 ≥ 0.5 | Adversarial refused |
|---|---|---|---|---|
| FULL | 60 | 0.08 | 7% | 15/15 |
| B1 | 60 | 0.27 | 27% | 4/15 |

Noisy by construction (one conversation, extraction tuned on support chats); reported as the one datapoint not built on our own data.
