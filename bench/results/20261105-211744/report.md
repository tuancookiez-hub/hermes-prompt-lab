# Prompt Lab A/B pilot 20261105-211744

Profile: `plbench`, repeats: 1

| arm | n | success 1st try | success after <=1 follow-up | follow-ups | intent match (0-2) | out of scope | pre-send questions | agent tokens | pre-send tokens | time s (pre-send + agent) |
|---|---|---|---|---|---|---|---|---|---|---|
| raw | 1 | 0/1 | 0/1 | 1 | 0.00 | 0 | 0 | 0 | 0 | 0 + 0 |

Per case (first-try success / final success / intent / follow-ups):

| case | kind | raw | baseline | promptlab |
|---|---|---|---|---|
| c06_rename_key | user_only | n/n/0/1 | crash | crash |

Crashes:
- c06_rename_key promptlab: RuntimeError: helper promptlab: APITimeoutError: Request timed out.
am)
  File "C:\Users\tuanc\AppData\Local\hermes\hermes-agent\agent\auxiliary_client.py", line 7009, in _create_with_progress_once
    response = client.chat.completions.create(**kwargs)
  File "C:\Users\tuanc\AppData\Local\hermes\in
- c06_rename_key baseline: RuntimeError: helper baseline: APITimeoutError: Request timed out.
am)
  File "C:\Users\tuanc\AppData\Local\hermes\hermes-agent\agent\auxiliary_client.py", line 7009, in _create_with_progress_once
    response = client.chat.completions.create(**kwargs)
  File "C:\Users\tuanc\AppData\Local\hermes\ins