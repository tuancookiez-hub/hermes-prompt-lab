# Pilot notes: read this before report.md

Run 20261106-234337, Hermes v0.23.0, profile `plbench`, agent model `tencent/hy4`.
Six prompts written for the pilot, not taken from real history. One repeat per arm.

**Verdict: no improvement can be claimed. On the valid paired data, Prompt Lab was slower and no more successful.**

## What is invalid in report.md

1. **The baseline arm is not a baseline.** In 5 of 6 cases the rewrite call returned empty text and a
   harness fallback silently sent the raw prompt. Those runs are raw-prompt runs. Only `c01` got a real rewrite.
2. **The arm means are not paired.** `c04` Prompt Lab crashed, so its mean drops the most expensive case.
   That makes Prompt Lab look cheaper than it was.
3. **Prompt Lab has no `c04` result.** The simulated user timed out twice, 180 s each, on two separate attempts.

## Paired result: raw vs Prompt Lab (5 cases, c04 excluded)

| | raw | Prompt Lab |
|---|---|---|
| First-try success | 5/5 | 5/5 |
| Follow-ups | 0 | 0 |
| Intent match (0-2) | 2.00 | 2.00 |
| Agent tokens, all | 223,735 | 204,092 |
| Agent tokens, uncached | 33,335 | 45,513 |
| Time, pre-send + agent | 125 s | 217 s |
| Questions the user must answer | 0 | 6 |

Time for a person to answer questions is not included.

| Case | Verdict | Uncached raw -> PL | Time raw -> PL |
|---|---|---|---|
| c01 | clear (model) | 17,537 -> 16,323 | 120 s -> 176 s |
| c02 | clear (pre-check) | 16,485 -> 10,876 | 84 s -> 112 s |
| c03 | ask, 3 questions | 49,761 -> 120,432 | 182 s -> 333 s |
| c05 | clear (model) | 19,676 -> 27,189 | 75 s -> 132 s |
| c06 | ask, 3 questions | 63,216 -> 52,745 | 165 s -> 331 s |

## Accidental A/A test: run-to-run noise

The five broken baseline runs sent exactly the same text as raw, so they measure noise.

| Case | Uncached, run 1 | Uncached, run 2 | First-try result |
|---|---|---|---|
| c02 | 16,485 | 12,778 | pass, pass |
| c03 | 49,761 | 47,562 | pass, pass |
| c04 | 218,563 | 123,252 | **fail, pass** |
| c05 | 19,676 | 39,161 | pass, pass |
| c06 | 63,216 | 76,446 | **pass, fail** |

The same prompt flipped pass/fail in 2 of 5 cases, and tokens varied by up to 2x.
Single-run differences of that size mean nothing.

## Findings

- **Ceiling effect.** Every completed run reached final success with intent 2.00, so those metrics could not
  separate the arms. The tasks are too easy, and intent is graded only after the follow-up.
- **Prompt Lab asks too much.** On `c03` it asked "Which report should be optimized?" in a repo with one report,
  because it sees only AGENTS/CLAUDE/README and no file list. Raw had passed without questions. That run was the
  most expensive Prompt Lab result. On `c06` only the first of three questions was necessary.
- **The pre-check worked.** `c02` got its verdict in 0 s with no model call.
- **hy4 is unreliable for short side calls.** The verbatim enhance-prompt call returned 65,536 output tokens and
  no text, about 6.5 minutes per call, even with `max_tokens=4000`. A Prompt Lab triage took 199 s, and the
  simulated user timed out.
- **Not tested:** the enhance-prompt Desktop button, which uses `llm.oneshot`, a different path from this one.
