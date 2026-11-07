# Prompt Lab A/B pilot 20261106-234337

Hermes Agent v0.23.0 (2026.9.24) · stable · local 2bd378ed1b8d

Profile: `plbench`, repeats: 1

| arm | n | success 1st try | success after <=1 follow-up | follow-ups | intent match (0-2) | out of scope | pre-send questions | agent tokens (all) | agent tokens (uncached) | pre-send tokens | time s (pre-send + agent) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| raw | 6 | 5/6 | 6/6 | 1 | 2.00 | 0 | 0 | 334,638 | 64,206 | 0 | 0 + 167 |
| baseline | 6 | 5/6 | 6/6 | 1 | 2.00 | 0 | 0 | 280,641 | 52,396 | 55,924 | 324 + 148 |
| promptlab | 5 | 5/5 | 5/5 | 0 | 2.00 | 0 | 6 | 204,092 | 45,513 | 1,737 | 58 + 159 |

Per case (first-try success / final success / intent / follow-ups):

| case | kind | raw | baseline | promptlab |
|---|---|---|---|---|
| c01_fix_tests | clear | Y/Y/2/0 | Y/Y/2/0 | Y/Y/2/0 |
| c02_json_flag | clear | Y/Y/2/0 | Y/Y/2/0 | Y/Y/2/0 |
| c03_faster_report | vague | Y/Y/2/0 | Y/Y/2/0 | Y/Y/2/0 |
| c04_clean_entries | vague | n/Y/2/1 | Y/Y/2/0 | crash |
| c05_parse_dates | project | Y/Y/2/0 | Y/Y/2/0 | Y/Y/2/0 |
| c06_rename_key | user_only | Y/Y/2/0 | n/Y/2/1 | Y/Y/2/0 |

Crashes:
- c04_clean_entries promptlab: RuntimeError: helper simuser: APITimeoutError: Request timed out.
am)
  File "C:\Users\tuanc\AppData\Local\hermes\hermes-agent\agent\auxiliary_client.py", line 7009, in _create_with_progress_once
    response = client.chat.completions.create(**kwargs)
  File "C:\Users\tuanc\AppData\Local\hermes\inst