# drift.py on Corner Shop traces

Action rows made from our own Corner Shop traces with `--from-corner-shop` (one row per purchase order, payment, liquidation or credit draw; no prompts or model text). Each pair is the same model with the end date seen and hidden. GPT-6.2-Sol shows the late-orders collapse; Qwen3.5-35B-A3B does not.

```
$ python -m period_end_check.drift --compare examples/drift/gpt-6.2-sol_hidden.jsonl examples/drift/gpt-6.2-sol_seen.jsonl --labels hidden seen --k 3
```
# End-of-period drift: seen vs hidden
window = last 3 steps

| Action type | Collapse hidden | Collapse seen | Change | Fisher p | Spike hidden | Spike seen | Median final/earlier hidden | seen |
|---|---|---|---|---|---|---|---|---|
| pay_invoice | 0/9 (0%) | 1/9 (11%) | +11 pts | 1 | 0/9 | 0/9 | 1.52 | 1.33 |
| purchase_order | 0/9 (0%) | 7/9 (78%) | +78 pts | 0.00226 | 0/9 | 0/9 | 1.05 | 0.21 |
| repay | 0/0 (n/a) | 0/0 (n/a) | n/a | n/a | 0/0 | 0/0 | n/a | n/a |


```
$ python -m period_end_check.drift --compare examples/drift/qwen3.5-35b-a3b_hidden.jsonl examples/drift/qwen3.5-35b-a3b_seen.jsonl --labels hidden seen --k 3
```
# End-of-period drift: seen vs hidden
window = last 3 steps

| Action type | Collapse hidden | Collapse seen | Change | Fisher p | Spike hidden | Spike seen | Median final/earlier hidden | seen |
|---|---|---|---|---|---|---|---|---|
| pay_invoice | 0/10 (0%) | 1/9 (11%) | +11 pts | 0.474 | 0/10 | 0/9 | 1.33 | 1.67 |
| purchase_order | 0/10 (0%) | 0/9 (0%) | +0 pts | 1 | 0/10 | 0/9 | 1.11 | 1.11 |
| repay | 0/0 (n/a) | 0/0 (n/a) | n/a | n/a | 0/0 | 0/0 | n/a | n/a |

