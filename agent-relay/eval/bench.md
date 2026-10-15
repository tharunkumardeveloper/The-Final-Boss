# Relay benchmarks

FalkorDB Cloud free tier, ap-south-1; client in India, ~24 ms RTT per query; writes include local fastembed embedding of message + entities.

## Concurrent writes + reads

| graphs | writes/s | write p50 | write p95 | reads during writes | read p50 | read p95 | dup entities | dup active facts | 0 active city | 2+ active city |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 18.3 | 352.8 ms | 700.7 ms | 63 | 310.1 ms | 484.2 ms | 0 | 0 | 0 | 0 |
| 4 | 23.7 | 346.8 ms | 411.4 ms | 65 | 272.5 ms | 355.0 ms | 0 | 0 | 0 | 0 |

## Recall latency vs graph size (no LLM)

| customers | facts | nodes | load | recall p50 | recall p95 | p50 per query |
|---|---|---|---|---|---|---|
| 200 | 1090 | 1577 | 0.9 s | 178.2 ms | 254.5 ms | known entities 42.7, vector seeds 47.4, retrieve facts 56.4 |
| 2000 | 10903 | 14990 | 11.1 s | 210.4 ms | 278.5 ms | known entities 71.2, vector seeds 41.8, retrieve facts 57.1 |
| 10000 | ceiling hit: command not allowed when used memory > 'maxmemory'. | | | | | |
