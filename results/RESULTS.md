# Benchmark results

Generated 2026-10-20 23:01 from `results/run-*.json` and `state/`.

### 6.1 Live OpenRouter experiment

> **Live OpenRouter runs** — real API calls, budget-capped (see the API budget table).

Runs included: **1** · generated 2026-10-20 23:01

#### Live (3 from solved) — exactly 3 moves from solved (BFS-verified) — 1 puzzle

| Model | Type | Trials | Solved | Success rate | Avg latency / move | Avg total time | Total moves | Avg moves (solved) | Avg optimal | Optimal gap | Gap = 0 | Cube completion | Invalid outputs | Retries | API calls | Cache hits | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jev 1.13 | Decision | 1 | 0 | 0% | 1109 ms | 21.66 s | 20 | – | 3.00 | – | 0/0 | 40.7% | 0 | 0 | 19 | 1 | 0.000855 |
| GPT-6 Luna Decisions | Decision | 1 | 0 | 0% | 1266 ms | 4.75 s | 1 | – | 3.00 | – | 0/0 | 40.7% | 0 | 1 | 2 | 1 | 0.000000 |
| Cloudflare Clef | Decision | 1 | 0 | 0% | 1084 ms | 21.01 s | 20 | – | 3.00 | – | 0/0 | 55.6% | 0 | 0 | 19 | 1 | 0.000717 |
| Claude Opus 5.5 | Frontier LLM | 1 | 1 | 100% | 16869 ms | 50.66 s | 3 | 3.00 | 3.00 | 0.00 | 1/1 | 100.0% | 0 | 0 | 3 | 0 | 0.065324 |

Fastest decisions: **Cloudflare Clef** · highest solve rate: **Claude Opus 5.5** · shortest solutions: **Claude Opus 5.5**

#### Per-puzzle results

| Run | Set | # | Scramble | Optimal | Jev 1.13 | GPT-6 Luna Decisions | Cloudflare Clef | Claude Opus 5.5 |
|---|---|---:|---|---:|---|---|---|---|
| `20261020-214228-8464` | live3 | 1 | `D' L2 R'` | 3 | ❌ 20 mv, 21.66 s (move_limit) | ❌ 1 mv, 4.75 s (api_error) | ❌ 20 mv, 21.01 s (move_limit) | ✅ 3 mv, 50.66 s |


### 6.2 Ollama experiments (local open models)

> **Ollama runs** — real local open models standing in for each slot (free, no API budget).

Runs included: **1** · generated 2026-10-20 23:01

#### Live (3 from solved) — exactly 3 moves from solved (BFS-verified) — 1 puzzle

| Model | Type | Trials | Solved | Success rate | Avg latency / move | Avg total time | Total moves | Avg moves (solved) | Avg optimal | Optimal gap | Gap = 0 | Cube completion | Invalid outputs | Retries | API calls | Cache hits | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jev 1.13 slot → `gemma3:1b` | Decision | 1 | 0 | 0% | 288 ms | 6.77 s | 20 | – | 3.00 | – | 0/0 | 40.7% | 0 | 0 | 20 | 0 | 0.000000 |
| GPT-6 Luna Decisions slot → `llama3.2:1b` | Decision | 1 | 0 | 0% | 232 ms | 5.66 s | 20 | – | 3.00 | – | 0/0 | 42.6% | 0 | 0 | 20 | 0 | 0.000000 |
| Cloudflare Clef slot → `qwen2.5:1.5b` | Decision | 1 | 0 | 0% | 292 ms | 6.91 s | 20 | – | 3.00 | – | 0/0 | 31.5% | 0 | 0 | 20 | 0 | 0.000000 |
| Claude Opus 5.5 slot → `qwen3:4b` | Frontier LLM | 1 | 0 | 0% | 123146 ms | 15:00.01 min | 6 | – | 3.00 | – | 0/0 | 37.0% | 1 | 0 | 7 | 0 | 0.000000 |

Fastest decisions: **GPT-6 Luna Decisions** · highest solve rate: **–** · shortest solutions: **–**

#### Per-puzzle results

| Run | Set | # | Scramble | Optimal | Jev 1.13 | GPT-6 Luna Decisions | Cloudflare Clef | Claude Opus 5.5 |
|---|---|---:|---|---:|---|---|---|---|
| `20261020-224108-5c01` | live3 | 1 | `D' L2 R'` | 3 | ❌ 20 mv, 6.77 s (move_limit) | ❌ 20 mv, 5.66 s (move_limit) | ❌ 20 mv, 6.91 s (move_limit) | ❌ 6 mv, 15:00.01 min (out_of_time) |


### 6.3 Mock runs (pipeline verification only)

> **Mock runs** — simulated models, no API calls. These only verify the pipeline.

Runs included: **6** · generated 2026-10-20 23:01

#### Primary benchmark (4–5 scramble turns) — 22 puzzles

| Model | Type | Trials | Solved | Success rate | Avg latency / move | Avg total time | Total moves | Avg moves (solved) | Avg optimal | Optimal gap | Gap = 0 | Cube completion | Invalid outputs | Retries | API calls | Cache hits | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jev 1.13 | Decision | 22 | 20 | 91% | 329 ms | 3.57 s | 236 | 8.80 | 4.36 | 4.40 | 8/20 | 95.1% | 0 | 0 | 0 | 0 | 0.000000 |
| GPT-6 Luna Decisions | Decision | 22 | 17 | 77% | 462 ms | 7.42 s | 349 | 11.71 | 4.36 | 7.41 | 3/17 | 86.1% | 0 | 0 | 0 | 0 | 0.000000 |
| Cloudflare Clef | Decision | 22 | 9 | 41% | 226 ms | 5.19 s | 486 | 10.67 | 4.36 | 6.44 | 3/9 | 63.3% | 0 | 0 | 0 | 0 | 0.000000 |
| Claude Opus 5.5 | Frontier LLM | 22 | 22 | 100% | 5457 ms | 25.80 s | 101 | 4.59 | 4.36 | 0.23 | 19/22 | 100.0% | 3 | 0 | 0 | 0 | 0.000000 |

Fastest decisions: **Cloudflare Clef** · highest solve rate: **Claude Opus 5.5** · shortest solutions: **Claude Opus 5.5**

#### Warm-up (3–4 scramble turns) — 3 puzzles

| Model | Type | Trials | Solved | Success rate | Avg latency / move | Avg total time | Total moves | Avg moves (solved) | Avg optimal | Optimal gap | Gap = 0 | Cube completion | Invalid outputs | Retries | API calls | Cache hits | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jev 1.13 | Decision | 3 | 3 | 100% | 346 ms | 3.83 s | 33 | 11.00 | 3.67 | 7.33 | 0/3 | 100.0% | 0 | 0 | 0 | 0 | 0.000000 |
| GPT-6 Luna Decisions | Decision | 3 | 2 | 67% | 523 ms | 6.75 s | 38 | 4.00 | 3.67 | 0.50 | 1/2 | 77.8% | 0 | 0 | 0 | 0 | 0.000000 |
| Cloudflare Clef | Decision | 3 | 2 | 67% | 208 ms | 2.92 s | 41 | 5.50 | 3.67 | 2.00 | 1/2 | 79.6% | 0 | 0 | 0 | 0 | 0.000000 |
| Claude Opus 5.5 | Frontier LLM | 3 | 3 | 100% | 5294 ms | 19.42 s | 11 | 3.67 | 3.67 | 0.00 | 3/3 | 100.0% | 0 | 0 | 0 | 0 | 0.000000 |

Fastest decisions: **Cloudflare Clef** · highest solve rate: **tie: Jev 1.13 & Claude Opus 5.5** · shortest solutions: **Claude Opus 5.5**

#### Extension (15–20 scramble turns) — 3 puzzles

| Model | Type | Trials | Solved | Success rate | Avg latency / move | Avg total time | Total moves | Avg moves (solved) | Avg optimal | Optimal gap | Gap = 0 | Cube completion | Invalid outputs | Retries | API calls | Cache hits | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jev 1.13 | Decision | 3 | 0 | 0% | 323 ms | 10.14 s | 90 | – | – | – | 0/0 | 38.9% | 0 | 0 | 0 | 0 | 0.000000 |
| GPT-6 Luna Decisions | Decision | 3 | 0 | 0% | 489 ms | 15.09 s | 90 | – | – | – | 0/0 | 34.0% | 0 | 0 | 0 | 0 | 0.000000 |
| Cloudflare Clef | Decision | 3 | 0 | 0% | 215 ms | 6.89 s | 90 | – | – | – | 0/0 | 38.3% | 0 | 0 | 0 | 0 | 0.000000 |
| Claude Opus 5.5 | Frontier LLM | 3 | 0 | 0% | 5836 ms | 2:57.40 min | 90 | – | – | – | 0/0 | 36.4% | 1 | 0 | 0 | 0 | 0.000000 |

Fastest decisions: **Cloudflare Clef** · highest solve rate: **–** · shortest solutions: **–**

#### All test sets — 28 puzzles

| Model | Type | Trials | Solved | Success rate | Avg latency / move | Avg total time | Total moves | Avg moves (solved) | Avg optimal | Optimal gap | Gap = 0 | Cube completion | Invalid outputs | Retries | API calls | Cache hits | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jev 1.13 | Decision | 28 | 23 | 82% | 329 ms | 4.30 s | 359 | 9.09 | 4.28 | 4.78 | 8/23 | 89.6% | 0 | 0 | 0 | 0 | 0.000000 |
| GPT-6 Luna Decisions | Decision | 28 | 19 | 68% | 472 ms | 8.17 s | 477 | 10.89 | 4.28 | 6.68 | 4/19 | 79.6% | 0 | 0 | 0 | 0 | 0.000000 |
| Cloudflare Clef | Decision | 28 | 11 | 39% | 223 ms | 5.13 s | 617 | 9.73 | 4.28 | 5.64 | 4/11 | 62.4% | 0 | 0 | 0 | 0 | 0.000000 |
| Claude Opus 5.5 | Frontier LLM | 28 | 25 | 89% | 5616 ms | 41.36 s | 202 | 4.48 | 4.28 | 0.20 | 22/25 | 93.2% | 4 | 0 | 0 | 0 | 0.000000 |

Fastest decisions: **Cloudflare Clef** · highest solve rate: **Claude Opus 5.5** · shortest solutions: **Claude Opus 5.5**

#### Per-puzzle results

| Run | Set | # | Scramble | Optimal | Jev 1.13 | GPT-6 Luna Decisions | Cloudflare Clef | Claude Opus 5.5 |
|---|---|---:|---|---:|---|---|---|---|
| `20261020-134939-623d` | primary | 1 | `R' B' D R'` | 4 | ❌ 30 mv, 10.91 s (move_limit) | ✅ 10 mv, 4.07 s | ❌ 30 mv, 6.88 s (move_limit) | ✅ 4 mv, 17.40 s |
| `20261020-134939-623d` | primary | 2 | `B2 R' F R2` | 4 | ✅ 6 mv, 1.91 s | ✅ 8 mv, 4.22 s | ✅ 20 mv, 4.19 s | ✅ 6 mv, 36.13 s |
| `20261020-134939-623d` | primary | 3 | `F2 B R2 B'` | 4 | ✅ 12 mv, 3.36 s | ❌ 30 mv, 14.11 s (move_limit) | ✅ 18 mv, 4.20 s | ✅ 4 mv, 19.54 s |
| `20261020-134939-623d` | primary | 4 | `D' L R2 B` | 4 | ✅ 10 mv, 3.38 s | ❌ 30 mv, 15.09 s (move_limit) | ❌ 30 mv, 7.23 s (move_limit) | ✅ 4 mv, 23.55 s |
| `20261020-134939-623d` | primary | 5 | `F2 U' F2 B' R2` | 5 | ✅ 9 mv, 2.68 s | ❌ 30 mv, 12.02 s (move_limit) | ✅ 5 mv, 1.14 s | ✅ 5 mv, 28.73 s |
| `20261020-134939-623d` | primary | 6 | `D' U2 R2 L` | 4 | ✅ 4 mv, 1.28 s | ✅ 4 mv, 1.79 s | ❌ 30 mv, 7.14 s (move_limit) | ✅ 4 mv, 18.76 s |
| `20261020-134939-623d` | primary | 7 | `B' F' R' U'` | 4 | ✅ 4 mv, 1.25 s | ✅ 28 mv, 13.54 s | ✅ 4 mv, 0.89 s | ✅ 4 mv, 15.86 s |
| `20261020-134939-623d` | primary | 8 | `L' F' U2 R2 D` | 5 | ✅ 14 mv, 4.82 s | ✅ 5 mv, 2.33 s | ❌ 30 mv, 7.44 s (move_limit) | ✅ 5 mv, 34.32 s |
| `20261020-134939-623d` | primary | 9 | `R2 L2 D' R'` | 4 | ✅ 4 mv, 1.84 s | ✅ 8 mv, 4.22 s | ✅ 11 mv, 2.68 s | ✅ 4 mv, 18.99 s |
| `20261020-134939-623d` | primary | 10 | `U2 R2 U2 R` | 4 | ✅ 4 mv, 1.12 s | ✅ 25 mv, 12.89 s | ❌ 30 mv, 6.48 s (move_limit) | ✅ 4 mv, 28.92 s |
| `20261020-134939-6515` | warmup | 1 | `B D F2` | 3 | ✅ 9 mv, 3.44 s | ✅ 3 mv, 1.58 s | ✅ 3 mv, 0.75 s | ✅ 3 mv, 16.61 s |
| `20261020-134939-6515` | warmup | 2 | `F B' L' U'` | 4 | ✅ 18 mv, 5.70 s | ❌ 30 mv, 16.29 s (move_limit) | ✅ 8 mv, 1.74 s | ✅ 4 mv, 21.59 s |
| `20261020-134939-6515` | warmup | 3 | `R' U R2 B` | 4 | ✅ 6 mv, 2.34 s | ✅ 5 mv, 2.37 s | ❌ 30 mv, 6.28 s (move_limit) | ✅ 4 mv, 20.05 s |
| `20261020-134940-e769` | extension | 1 | `D2 U2 L' B2 F2 D' F L B R D2 B2 F2 D U2 L' U' D F' D'` | – | ❌ 30 mv, 9.65 s (move_limit) | ❌ 30 mv, 14.14 s (move_limit) | ❌ 30 mv, 7.19 s (move_limit) | ❌ 30 mv, 2:56.32 min (move_limit) |
| `20261020-134940-e769` | extension | 2 | `U2 R' L' B' R2 L2 F' D2 U F U L' R2 F' D2 F B D` | – | ❌ 30 mv, 10.62 s (move_limit) | ❌ 30 mv, 15.54 s (move_limit) | ❌ 30 mv, 6.75 s (move_limit) | ❌ 30 mv, 3:05.05 min (move_limit) |
| `20261020-134940-e769` | extension | 3 | `B U' R2 U L F' R' U' L2 D2 B R' D R2 B' R2` | – | ❌ 30 mv, 10.16 s (move_limit) | ❌ 30 mv, 15.61 s (move_limit) | ❌ 30 mv, 6.74 s (move_limit) | ❌ 30 mv, 2:50.83 min (move_limit) |
| `20261020-141331-3f31` | primary | 1 | `B D' L2 B2 U` | 5 | ✅ 5 mv, 1.76 s | ❌ 30 mv, 14.56 s (move_limit) | ❌ 30 mv, 7.35 s (move_limit) | ✅ 5 mv, 36.55 s |
| `20261020-141331-3f31` | primary | 2 | `B U2 R U2` | 4 | ✅ 4 mv, 1.08 s | ✅ 6 mv, 2.40 s | ✅ 4 mv, 0.84 s | ✅ 6 mv, 30.58 s |
| `20261020-141331-3f31` | primary | 3 | `U R U2 R B` | 5 | ✅ 28 mv, 9.30 s | ✅ 8 mv, 4.59 s | ❌ 30 mv, 6.94 s (move_limit) | ✅ 6 mv, 36.83 s |
| `20261020-141331-3f31` | primary | 4 | `B L' R D2` | 4 | ✅ 24 mv, 8.05 s | ✅ 19 mv, 7.76 s | ✅ 6 mv, 1.31 s | ✅ 4 mv, 19.78 s |
| `20261020-141344-69c2` | primary | 1 | `U R B' D` | 4 | ✅ 9 mv, 3.03 s | ✅ 17 mv, 6.84 s | ❌ 30 mv, 7.33 s (move_limit) | ✅ 4 mv, 23.00 s |
| `20261020-141344-69c2` | primary | 2 | `B2 R B R' U` | 5 | ✅ 8 mv, 2.46 s | ✅ 14 mv, 6.20 s | ✅ 22 mv, 5.36 s | ✅ 5 mv, 22.29 s |
| `20261020-141344-69c2` | primary | 3 | `B2 F2 L D2 R'` | 5 | ✅ 7 mv, 2.71 s | ✅ 5 mv, 2.97 s | ❌ 30 mv, 6.58 s (move_limit) | ✅ 5 mv, 21.07 s |
| `20261020-141344-69c2` | primary | 4 | `D2 R' B' U` | 4 | ❌ 30 mv, 10.51 s (move_limit) | ✅ 18 mv, 7.43 s | ❌ 30 mv, 7.66 s (move_limit) | ✅ 4 mv, 24.93 s |
| `20261020-141344-69c2` | primary | 5 | `F2 D R' U2` | 4 | ✅ 6 mv, 1.85 s | ✅ 6 mv, 2.65 s | ✅ 6 mv, 1.26 s | ✅ 4 mv, 19.40 s |
| `20261020-141357-d9a8` | primary | 1 | `B' U' D2 L U2` | 5 | ✅ 5 mv, 1.56 s | ❌ 30 mv, 13.88 s (move_limit) | ❌ 30 mv, 7.29 s (move_limit) | ✅ 5 mv, 36.48 s |
| `20261020-141357-d9a8` | primary | 2 | `D R' F D2` | 4 | ✅ 4 mv, 0.92 s | ✅ 9 mv, 4.97 s | ❌ 30 mv, 6.90 s (move_limit) | ✅ 4 mv, 22.72 s |
| `20261020-141357-d9a8` | primary | 3 | `D2 B' U F L2` | 5 | ✅ 9 mv, 2.82 s | ✅ 9 mv, 4.75 s | ❌ 30 mv, 7.08 s (move_limit) | ✅ 5 mv, 31.82 s |


### 6.4 OpenRouter API budget (persistent counter, all attempts incl. retries/failures)

Total actual requests: **46 / 65** (key hard limit 100) · Claude limit 5 · decision-model limit 20 each · actual cost reported by OpenRouter: **$0.067044** · cached responses: 901

| Model | Actual requests |
|---|---:|
| `anthropic/claude-opus-5.5` | 3 |
| `cloudflare/clef` | 20 |
| `openai/gpt-6-luna-decisions` | 3 |
| `typesafe/jev-1.13` | 20 |
