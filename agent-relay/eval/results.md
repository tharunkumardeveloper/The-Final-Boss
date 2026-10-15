# Relay benchmark

Tenant `pml`: 40 customers, 556 customer turns, 160 questions. Answer models alternate per question (`gemini:gemini-3.5-flash`, `qwen/qwen3.8-27b`); for each question every system uses the same model and prompt. Intervals are 95% Wilson.

## All systems

| System | What it is | Questions | Accuracy [95% CI] | Evidence recall | Retrieval p50 / p95 ms |
|---|---|---|---|---|---|

## Abstention (should-refuse questions)

| System | Precision | Recall | Hallucinated answers | False refusals |
|---|---|---|---|---|

## Per answer model

| System | gemini:gemini-3.5-flash | qwen/qwen3.8-27b |
|---|---|---|
