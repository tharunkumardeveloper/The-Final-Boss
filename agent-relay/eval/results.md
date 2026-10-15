# Relay benchmark

Tenant `pml-bench`: 40 customers, 556 customer turns, 160 questions. Answer models alternate per question (`qwen/qwen3.8-27b`, `groq2:qwen/qwen3.8-27b`, `groq3:qwen/qwen3.8-27b`, `groq4:qwen/qwen3.8-27b`, `groq5:qwen/qwen3.8-27b`); for each question every system uses the same model and prompt. Intervals are 95% Wilson.

## Headline

On the 160 questions both systems answered: **Relay 69%** [61%–75%] vs **vector baseline (B1) 55%** [47%–62%].

## Gap decomposition by question type (directional: ~16–18 questions per type, wide intervals)

| Type | n | Relay | B1 vector | Δ |
|---|---|---|---|---|
| belief_time | 18 | 78% [55%–91%] | 89% [67%–97%] | -11 pts |
| completeness | 18 | 100% [82%–100%] | 44% [25%–66%] | +56 pts |
| current | 18 | 94% [74%–99%] | 72% [49%–88%] | +22 pts |
| disagreement | 16 | 0% [0%–19%] | 0% [0%–19%] | +0 pts |
| handoff | 18 | 100% [82%–100%] | 83% [61%–94%] | +17 pts |
| multi_hop | 18 | 28% [12%–51%] | 0% [0%–18%] | +28 pts |
| procedural | 18 | 56% [34%–75%] | 44% [25%–66%] | +11 pts |
| unknown | 18 | 67% [44%–84%] | 72% [49%–88%] | -6 pts |
| world_time | 18 | 89% [67%–97%] | 83% [61%–94%] | +6 pts |

Simple recall (`current`, `handoff`) is where a good vector store should stay competitive; the gap should come from updates over time, disagreement, multi-hop and abstention.

## All systems

| System | What it is | Questions | Accuracy [95% CI] | Evidence recall | Retrieval p50 / p95 ms |
|---|---|---|---|---|---|
| FULL | Relay: graph expansion + two clocks + conflict ranking | 160/160 | 69% [61%–75%] | 82% | 258.5 / 313.5 |
| B1 | Vector store: customer-filtered, top-10, dated, newest first | 160/160 | 55% [47%–62%] | 73% | 45.0 / 51.6 |

## Abstention (should-refuse questions)

| System | Precision | Recall | Hallucinated answers | False refusals |
|---|---|---|---|---|
| FULL | 52% | 67% | 6 | 11 |
| B1 | 34% | 72% | 5 | 25 |

## Per answer model

| System | qwen/qwen3.8-27b | groq2:qwen/qwen3.8-27b | groq3:qwen/qwen3.8-27b | groq4:qwen/qwen3.8-27b | groq5:qwen/qwen3.8-27b |
|---|---|---|---|---|---|
| FULL | 66% [48%–80%] | 75% [58%–87%] | 81% [65%–91%] | 62% [39%–82%] | 62% [45%–77%] |
| B1 | 59% [42%–74%] | 53% [36%–69%] | 66% [48%–80%] | 50% [28%–72%] | 59% [42%–74%] |
