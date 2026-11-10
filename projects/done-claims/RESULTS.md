# Unverified submissions in 51,087 SWE-agent runs

In 18,640 of the 47,293 submissions that changed product code (39.4%), the agent ran nothing after its last edit and submitted anyway. Those submissions resolved the issue 18.2% of the time. Submissions whose last run after the edit showed no failure resolved it 34.0% of the time. Comparing attempts at the same issue, the Mantel-Haenszel odds ratio is 0.68 (95% CI 0.63 to 0.74, 598 issues).

The data is [nebius/SWE-agent-trajectories](https://huggingface.co/datasets/nebius/SWE-agent-trajectories) at revision `68195a1450865274106246d0d0296a1d6807b88e`, licensed CC BY 4.0. It holds 80,036 trajectories from SWE-agent driven by three Llama-based action models (`swe-agent-llama-8b`, `-70b` and `-405b`) on SWE-bench-extra and the SWE-bench dev split. Each trajectory is labelled by whether its final patch passed the tests of the linked pull request. The dataset card asks anyone using the model outputs to follow the Llama 3.1 license; this study redistributes no trajectory text. This analysis keeps the 51,087 runs with exit status `submitted`, where the agent called `submit` itself. The other 28,949 are left out: 21,026 were submitted automatically when the context window filled up, 6,744 stopped without a submit, 1,066 submitted an empty patch and 113 ended on format or cost limits.

For each trajectory, the classifier in `doneclaims/` finds the last applied edit to a product file and looks at what ran after it.

- Product files are the files in the final patch that are not tests, documentation, build artifacts or scratch scripts. A scratch script sits at the repository root with a name like `reproduce*.py`, or inside a root-level directory like `tmp_app/`; `dvc/repo/reproduce.py` is product code.
- An edit is an SWE-agent `edit` or `create` command that the environment did not reject, or a shell write: `sed -i`, redirection, `tee`, `mv`, `cp`, `rm`.
- A run is a test runner (pytest, unittest, nose2, tox and others) or a script (`python file.py`, `python -c`, `python -m module`, `bash file.sh`, a `.py` or `.sh` file called by its path). Commands inside `bash -c "..."` count as if typed directly. Linters, type checkers, `pip install`, `python -m pip`, `python -m venv` and `setup.py install`, `develop` or `build` are not runs.
- A run fails when its output has a traceback, a pytest or unittest failure summary, a pytest summary in which no test passed, a timeout or a missing script. It passes when it shows a passing summary or SWE-agent's "Script completed successfully" line. Anything else is a run with no failure signal.

| Category | Meaning |
|---|---|
| `unverified` | nothing ran after the last product edit |
| `ran_failing` | the last run after the edit failed |
| `ran_passing` | the last run after the edit showed no failure signal |
| `no_product_change` | the patch touches no product file |
| `undetermined` | product files changed, but no edit to them is visible in the trajectory |

## Results

| Category | Submissions | Resolved | Rate | 95% CI (Wilson) |
|---|---:|---:|---:|---|
| `unverified` | 18,640 | 3,386 | 18.2% | 17.6 to 18.7 |
| `ran_failing` | 3,634 | 893 | 24.6% | 23.2 to 26.0 |
| `ran_passing` | 24,616 | 8,381 | 34.0% | 33.5 to 34.6 |
| `undetermined` | 403 | 7 | 1.7% | 0.8 to 3.5 |
| `no_product_change` | 3,794 | 5 | 0.1% | 0.1 to 0.3 |

Odds ratios below are Mantel-Haenszel estimates with Robins-Breslow-Greenland intervals. Each stratum is one issue, or one issue and model. Only strata where both groups occur and outcomes differ contribute.

| Comparison | Within issue | Strata | Within issue and model | Strata |
|---|---|---:|---|---:|
| `unverified` vs `ran_passing` | 0.682 (0.625 to 0.744) | 598 | 0.696 (0.637 to 0.760) | 630 |
| `ran_failing` vs `ran_passing` | 0.650 (0.564 to 0.748) | 434 | 0.659 (0.572 to 0.760) | 446 |
| `unverified` with a success claim vs without | 1.212 (1.043 to 1.408) | 371 | 1.215 (1.045 to 1.413) | 382 |
| `ran_passing` after a test run vs a script only | 0.994 (0.780 to 1.267) | 200 | 0.982 (0.768 to 1.254) | 201 |

Task difficulty explains part of the raw gap. The crude odds ratio for `unverified` against `ran_passing` is 0.43. Within the same issue it is 0.68, so a comparison that ignores the issue overstates the effect.

Submitting after a failing run is about as bad as submitting without one: 0.65 within issue. In the audit sample, failing runs were often environment failures (a missing module, missing credentials, a network call) rather than evidence that the fix was wrong.

The closing message is a weak signal. With the lexicon in `doneclaims/rules.py` ("verified", "confirmed", "tests pass", "has been fixed", without a hedge or a negation in the same sentence), 3,096 of the 18,640 unverified submissions (16.6%) assert success. They resolved 20.8% of the time against 17.6% for the other unverified submissions, and the within-issue odds ratio is above 1.

Running the test suite did not beat running a script. The 1,159 `ran_passing` submissions with a test run after the edit resolved 31.9%; the 23,457 that only ran a script resolved 34.2%. An explicit pass (4,990 submissions, 33.6%) and a run with no failure signal (19,626, 34.2%) also resolve at the same rate.

| Model | `unverified` | `ran_passing` |
|---|---|---|
| swe-agent-llama-8b | 700 submissions, 16.4% | 935 submissions, 35.9% |
| swe-agent-llama-70b | 17,841 submissions, 18.1% | 23,336 submissions, 33.6% |
| swe-agent-llama-405b | 99 submissions, 50.5% | 345 submissions, 58.3% |

## Checking the classifier

Two random samples of 40 submissions each, 10 per category, were read step by step against the rules above (seeds 20261105 and 20261106).

The first sample found three classes of error, all in `undetermined` or in the list of product files: build artifacts such as `.egg-info` and `__pycache__` counted as product code, an edit whose body contained triple backticks broke command extraction, and `mv` was not read as a write. The second sample, drawn after those fixes, found one more: `rm` of a product file was not read as a write. Each fix came with a unit test and a full re-run, and every existing sample was re-checked. The fixes moved exactly the rows they targeted, plus one: after the `rm` fix, a first-sample run in which the agent deleted two generated dvc files and re-ran the script that rebuilt them moved from `undetermined` to `ran_passing`.

Reading Claude Code transcripts for phase 2 turned up two more errors. The scratch-name rule matched files anywhere in the tree, so product files such as `dvc/repo/reproduce.py` and `confuse/templates.py` were dropped as scratch in 208 submitted patches. The rule now applies only at the repository root and to root-level scratch directories. And an unquoted `pip install pkg>=3.6.0` makes the shell write a file named `=3.6.0`, which counted as product code. These fixes moved 169 submissions, none of them resolved and none in the audit samples.

The phase 2 audit, described below, found four rules that also apply here: `python -m pip install` counted as a run, a script called by its path and a command inside `bash -c "..."` did not, and a `pytest -q` summary, printed without the `=====` bars, was not read. Fixing them moved 15 more submissions, one of them resolved and none audited. Across all fixes, the within-issue odds ratio moved from 0.695 to 0.682.

Under the final rules, 64 of the 80 audited rows fall in the three main categories. None is misclassified and two are ambiguous: the dvc run above, and a script that caught an exception, printed it, and then printed its success line. The Wilson 95% interval for 64 of 64 is 0.943 to 1.000, or 0.893 to 0.991 if both ambiguous rows count as errors. The audit was done by the AI agent that wrote the classifier; a human re-check of the same 80 rows has not been done yet.

## Limitations

- The study is observational. Agents that verify may differ in ways that stratifying by issue and model does not capture, such as how early they found the right file.
- It covers one harness and one model family from 2024. Claude Code, Codex and Cursor phrase their closing messages differently, so the claim-language result in particular may not transfer.
- No failure signal is not success. A script that prints a wrong answer without raising counts as `ran_passing`.
- Files written by commands, such as lock files, CSV output and databases, count as product files. Edits made by a Python script or a download are not modelled. Most of these cases end up in `undetermined`.
- Within-issue estimates use 598 issues, the ones where both groups occur and outcomes differ.

## Phase 2a: Claude Code with gpt-oss-120b

Phase 2a runs the unmodified Claude Code CLI (2.1.318) inside Harbor 0.25.0 on SWE-bench Verified, with `openai/gpt-oss-120b` served by vLLM 0.33.0 on one H200 of the measurement machine. Every issue gets one appended sentence asking for a code change; [PLAN.md](PLAN.md) gives the reason and the design. All 1,500 planned trials (500 issues, 3 attempts) have a result. Trials that failed for infrastructure reasons, such as a Claude Code install over Harbor's 360-second limit or a container that did not start, were run again until none was left. 1,469 ended with the agent stopping on its own and the verifier writing a reward. The other 31 are kept as exceptions: 17 agents ran past the 50-minute limit, 5 hit the output token limit, 5 verifier runs timed out, 2 left no reward file and 2 agents exited with an error.

| Category | Trials | Resolved | Rate | 95% CI (Wilson) |
|---|---:|---:|---:|---|
| `unverified` | 194 | 80 | 41.2% | 34.5 to 48.3 |
| `ran_failing` | 572 | 324 | 56.6% | 52.6 to 60.6 |
| `ran_passing` | 675 | 393 | 58.2% | 54.5 to 61.9 |
| `no_product_change` | 28 | 0 | 0.0% | 0.0 to 12.1 |

The raw gap points the same way as in phase 1: trials that ran nothing after the last edit resolved the issue 17 points less often. Within the same issue the gap disappears. The odds ratio for `unverified` against `ran_passing` is 1.04 (0.42 to 2.55) from 22 issues, and 0.96 (0.39 to 2.41) without the 47 trials that fetched anything from the network. Most of the raw gap therefore comes from the issues on which the agent skips verification, not from skipping it on a given issue. The interval is wide and still contains the phase 1 estimate of 0.68. 95 issues have both kinds of attempt, but only 22 have the mix of categories and outcomes the estimate can use: `unverified` is 13.5% of trials that changed product code, and 365 of 499 issues are resolved by every attempt or by none.

The other within-issue comparisons are just as wide. `ran_failing` against `ran_passing` is 0.93 (0.56 to 1.57, 61 issues). A test run against a script only is 1.69 (0.52 to 5.47, 12 issues); in raw rates it reverses phase 1, 65.6% of 285 against 52.8% of 390. Among unverified trials, the 33 that claim success resolved 42.4% against 41.0% for the rest; no issue has both.

Two things about this setup shape the categories:

- The agent's shell runs the image's base Python 3.11, not the task's environment that the verifier uses, so test runs often stop at `No module named ...` or `pytest: command not found`. Most of the 20 audited `ran_failing` trials ended on such an environment error, not on a test of the change, which is why `ran_failing` and `ran_passing` resolve at the same rate. A run with an explicit passing summary resolved 69.3% of 140, a run with no failure signal 55.3% of 535; in phase 1 the two were equal (33.6% and 34.2%).
- gpt-oss-120b sometimes ends a session by printing raw chat-format tokens instead of a message or a tool call. 24 completed trials end this way, 11 of them without any product change.

Because the environment blurs what a run shows, phase 2a is reported as a description, not as the test of H1. Phase 2b repeats the run with the task environment on the agent's path and a pre-registered second stage of extra attempts on issues where the agent's behaviour varies (decision record #26, design in PLAN.md before it starts).

The adapter was audited on two random samples of 40 trials, 10 per category, drawn when 1,098 trials had completed (seeds 20261107 and 20261108). The first sample found two errors: helper files the agent created and deleted again, such as a stub `asgiref` package, counted as the last product edit; and edits sent with a `path` argument instead of `file_path`, which Claude Code applies anyway, were missed. The second sample, drawn after those fixes, found two more: a script called by its path and a test run inside `bash -lc "..."` were not read as runs. It also showed that Claude Code moves a command that hits its two-minute limit to the background, which now counts as a failed run, as a timeout already did in phase 1. On the second sample, 38 of 40 rows were right under the rules of the time (Wilson 95% interval 0.835 to 0.986). Under the final rules all 80 audited rows match a reading by hand. As in phase 1, the audit was done by the agent that wrote the classifier, and no human has re-checked it yet.

## Phase 2b: the pre-registered test of H1

Phase 2b reruns phase 2a with the four environment changes in [PLAN.md](PLAN.md), all fixed before it started: the task's environment on the agent's path, a prebuilt Claude Code binary, 12 trials at once instead of 16, and the model's real context window. Stage 1 gave each of the 500 issues three attempts; 1,437 of the 1,500 trials completed. 191 of the 1,407 completed trials that changed product code were `unverified` (13.6%), above the 8% gate, so stage 2 gave each of the 147 issues with an `unverified` stage-1 attempt 8 more attempts, the k that `doneclaims.power` picked before stage 2 started. Stage 2 completed 1,103 of 1,176 trials: 69 agents ran past the 50-minute limit, 3 trials left no reward file and 1 verifier timed out. On 10 November the job was paused for 47 minutes so another measurement could use the machine, and the 16 trials it cut off ran again. Every number below comes from the `doneclaims` sources recorded before stage 2 (SHA-256 `c0b6a8c4…`).

Stages 1 and 2 pooled over the 147 issues:

| Category | Trials | Resolved | Rate | 95% CI (Wilson) |
|---|---:|---:|---:|---|
| `unverified` | 463 | 201 | 43.4% | 39.0 to 48.0 |
| `ran_failing` | 270 | 146 | 54.1% | 48.1 to 59.9 |
| `ran_passing` | 761 | 427 | 56.1% | 52.6 to 59.6 |
| `no_product_change` | 41 | 0 | 0.0% | 0.0 to 8.6 |

Within the same issue, the Mantel-Haenszel odds ratio of resolution for `unverified` against `ran_passing` is 0.55 (Robins-Breslow-Greenland 95% CI 0.37 to 0.82), from the 73 issues where both categories occur and outcomes differ. The upper end is below 1, so H1 holds by the rule fixed in advance. Without the trials that fetched anything from the network it is 0.53 (0.35 to 0.80, 72 issues), and without the 38 stage-1 trials that ran on the one-GPU server it is 0.57 (0.38 to 0.86, 71 issues). Phase 1 measured 0.68 (0.63 to 0.74) on SWE-agent runs.

The secondary comparisons, pooled, stay close to 1: `ran_failing` against `ran_passing` is 0.92 (0.57 to 1.50, 57 issues), a success claim among `unverified` trials 1.04 (0.43 to 2.49, 21 issues), and a test run against a script only among `ran_passing` trials 1.01 (0.58 to 1.74, 42 issues). Among `ran_passing` trials, an explicit passing summary resolved 59.6% of 280 and a run with no failure signal 54.1% of 481. Stage 1 alone, over its 498 issues, gives 0.78 (0.38 to 1.61) for `unverified` against `ran_passing`, from 31 issues.

The classifier was audited before any pooled number was computed, on two random samples of 40 completed stage-1 trials, 10 per category (seeds 20261110 and 20261111). Two auditor agents built on different model families (GPT-5.6 Sol and Gemini 4 Argon) read all 80 rows independently against the definitions, and the agent that wrote the classifier re-read the 8 rows either of them did not call right, with the full output of each call. 78 rows are right (Wilson 95% interval 0.913 to 0.993), one is wrong and one is ambiguous. In the wrong row the agent's only product edit was `django/test/testcases.py`: the rule that treats files under a `test`, `tests` or `testing` directory as tests also catches Django's shipped test framework, so the trial counted as `no_product_change` instead of `unverified`. The ambiguous row edited only files inside a third-party project the agent had placed in the working tree. The other six disputes came from the three output lines an audit view shows, or from two definitions: `python -m py_compile` is a static check rather than a run, and a test run killed with exit code 137 counts as failed. Counting `test` and `testing` subpackages of the main package as product code moves 3 of the 2,540 completed trials, none of them resolved and all in issues where no `unverified` or `ran_passing` trial resolved, so H1 does not move; the numbers above keep the frozen rule. Instead of a human re-check, a jury of four language models from different families (GPT-5.6 Sol, Gemini 4 Argon, Grok 4.7 and Muse Wonder 1.0) re-read all 80 rows without seeing the earlier verdicts, with the full output of every run after the last product edit. All four agreed with the final verdict on 79 rows, the wrong one included; on the ambiguous row two called the classifier right, one wrong and one ambiguous. No human has re-checked the rows.

The 147 issues are the ones where the agent skipped verification at least once in stage 1, so the pooled estimate describes those issues, with one model in one harness. As in phase 1, the comparison is observational.

## Reproduce

Commands run from `projects/done-claims` with the repository's uv environment (Python 3.12.14, pyarrow 26.0.1, huggingface_hub 2.4.0).

1. `uv run python -m doneclaims.fetch` downloads the 12 Parquet shards (1,114,367,701 bytes) anonymously into `data/cache/done-claims/`.
2. `uv run python -m doneclaims.study --workers 6` classifies all 80,036 trajectories in about 20 seconds and writes `results/`.
3. `uv run python -m unittest discover -s tests -t .` runs the 86 unit tests.
4. `uv run python -m doneclaims.audit --recheck results/audit_pass2.csv --out results/audit_check.csv` re-renders an audit sample with the current rules; the views go to `data/cache/done-claims/audit/` and stay out of git.
5. Phase 2 runs on a GPU machine: `phase2/serve.sh gpt-oss-120b 0 8300`, then `phase2/run_harbor.sh JOB 3 16 --extra-instruction "..."` with the sentence from PLAN.md, and `phase2/collect.sh JOB` to pack the transcripts. `uv run python -m doneclaims.harbor JOB_DIR` classifies the trials and writes `results/phase2/JOB/`; `uv run python -m doneclaims.audit_harbor JOB_DIR results/phase2/JOB/trials.csv --recheck results/phase2/JOB/audit_pass2.csv --out ...` re-renders an audit sample. Transcripts stay out of git.
6. `uv run python -m doneclaims.phase2b results/phase2b/p2b-stage1/trials.csv results/phase2b/p2b-stage2/trials.csv` recomputes phase 2b into `results/phase2b/analysis.json`; `phase2/without_trials.py` drops the one-GPU trials for the sensitivity run.

`results/summary.json` records the dataset revision, the SHA-256 of the `doneclaims` sources (`88b6310b8e7de71b0745a283f435d80c965c437ee9eb9452b9d0c1da6ec5f8bf` for the numbers above), the library versions and the run time.

| File | Contents |
|---|---|
| `results/features.csv.gz` | one row per trajectory: ids, label, category, run counts; no trajectory text |
| `results/summary.json` | every number in this file |
| `results/audit_pass1.csv` | first sample, verdicts under the first version of the rules |
| `results/audit_recheck.csv`, `results/audit_pass1_final.csv` | the first sample after each round of fixes |
| `results/audit_pass2.csv`, `results/audit_pass2_recheck.csv` | second sample, before and after the `rm` fix |
| `results/phase2/full-gptoss-instr/trials.csv` | one row per phase 2 trial: status, reward, category, run counts, tokens; no transcript text |
| `results/phase2/full-gptoss-instr/summary.json` | the phase 2 numbers above, with Harbor, Claude Code and dataset versions |
| `results/phase2/full-gptoss-instr/audit_pass1*.csv` | first phase 2 sample under the first rules and after each round of fixes |
| `results/phase2/full-gptoss-instr/audit_pass2*.csv` | second phase 2 sample, before and after the second round of fixes |
| `results/phase2b/p2b-stage1/trials.csv`, `results/phase2b/p2b-stage2/trials.csv` | one row per phase 2b trial, trial names aliased; no transcript text |
| `results/phase2b/p2b-stage1/summary.json`, `results/phase2b/p2b-stage2/summary.json` | per-stage numbers with Harbor, Claude Code and dataset versions |
| `results/phase2b/analysis.json` | the phase 2b numbers above |
| `results/phase2b/p2b-stage1/audit_pass1.csv`, `audit_pass2.csv` | the stage-1 audit: final verdict and note, and each auditor's verdict |
| `results/phase2b/p2b-stage1/jury_pass1.csv`, `jury_pass2.csv` | the jury re-check: each juror's verdict, category and note next to the final verdict |
| `results/phase2b/stage2_issues.txt`, `results/phase2b/stage1_one_gpu_trials.txt` | the stage-2 issue set and the 38 trials from the one-GPU server |
