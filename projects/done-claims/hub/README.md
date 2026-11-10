---
license: cc-by-4.0
language:
- en
pretty_name: done-claims - coding agents that submit without running anything after their last edit
task_categories:
- tabular-classification
size_categories:
- 10K<n<100K
source_datasets:
- nebius/SWE-agent-trajectories
- SWE-bench/SWE-bench_Verified
annotations_creators:
- no-annotation
language_creators:
- found
tags:
- agents
- coding-agents
- swe-bench
- software-engineering
- evaluation
configs:
- config_name: phase1_swe_agent
  data_files: data/phase1/features.csv.gz
- config_name: phase2a_claude_code
  data_files: data/phase2a/trials.csv
- config_name: phase2b_stage1
  data_files: data/phase2b/stage1.csv
- config_name: phase2b_stage2
  data_files: data/phase2b/stage2.csv
---

# done-claims

In 18,640 of 47,293 submitted SWE-agent runs that changed product code (39.4%), the agent ran nothing after its
last edit. Those submissions resolved the issue 18.2% of the time, against 34.0% for submissions whose last run
after the edit showed no failure signal; comparing attempts at the same issue, the Mantel-Haenszel odds ratio is
0.68 (95% CI 0.63 to 0.74, 598 issues). A pre-registered rerun with Claude Code driven by gpt-oss-120b on SWE-bench
Verified gives 0.55 (95% CI 0.37 to 0.82, 73 issues).

This dataset holds the measurements behind those numbers, one row per trajectory or trial, with its category, run
counts and outcome. It contains no trajectory or transcript text. The classifier, the pre-registration and every
number with its source are at [github.com/speker/done-claims](https://github.com/speker/done-claims)
(`projects/done-claims/RESULTS.md` and `PLAN.md`).

## Files and columns

| Config | Rows | One row is |
|---|---:|---|
| `phase1_swe_agent` | 80,036 | a trajectory of nebius/SWE-agent-trajectories (revision `68195a1`); the analysis keeps the 51,087 whose exit status is `submitted` |
| `phase2a_claude_code` | 1,500 | a Claude Code trial on SWE-bench Verified in phase 2a, reported as a description only |
| `phase2b_stage1` | 1,500 | a trial of pre-registered stage 1: 500 issues, 3 attempts each |
| `phase2b_stage2` | 1,176 | a trial of stage 2: the 147 issues with an `unverified` stage-1 attempt, 8 more attempts each |

`results/` holds the summaries, the phase 2b analysis (`results/phase2b/analysis.json`) and every audit file, in the
same layout as the GitHub repository. The columns:

- `category`: `unverified` (nothing ran after the last product edit), `ran_failing` (the last run after it failed),
  `ran_passing` (the last run after it showed no failure signal), `no_product_change`; phase 1 also has
  `undetermined` (product files changed, but no edit to them is visible). The full definitions of a product file,
  an edit, a run and a failure are in RESULTS.md.
- `target`: whether the issue was resolved. Phase 1 takes the dataset's label (the final patch passed the tests of
  the linked pull request); phase 2 sets it when the SWE-bench verifier's reward is 1.
- `n_steps`, `n_product_files`, `touched_tests` (a patched or edited file is a test file), `last_product_edit` (step index), `runs_after_edit`,
  `tests_after_edit`, `last_outcome` (`pass`, `fail`, `unknown`, empty when nothing ran), `claims_success` (the
  closing message asserts success without a hedge or a negation, by the lexicon in `doneclaims/rules.py`).
- Phase 1 only: `shard` and `row` (position in the source Parquet shards), `instance_id`, `model_name` (the
  SWE-agent action model), `exit_status`.
- Phase 2 only: `trial` (`<instance_id>__s1-NN`, `s2-NN` in stage 2), `status` (`completed` or the exception type),
  `reward`, `remote_fetches` (shell commands that reached a URL or a git remote), `input_tokens`, `output_tokens`,
  `agent_seconds`.

## How the categories were checked

Each phase was audited on two random samples of 40 rows (10 per category in phase 2). In phase 2b, two auditor agents built on
different model families read the 80 stage-1 rows independently and the agent that wrote the classifier re-read the
rows they disputed: 78 are right, one is wrong (a file under `django/test/`, which ships with Django, was taken for a
test) and one is ambiguous. Instead of a human re-check, a jury of four language models from different families
re-read all 80 rows without seeing those verdicts. All four agreed with the final verdict on 79 rows, the wrong
one included; on the ambiguous row two called the classifier right, one wrong and one ambiguous. No human has
re-checked the rows. Fixing the `django/test/` rule moves 3 of
the 2,540 completed phase 2b trials and leaves the pre-registered estimate unchanged.

## Limitations

- The comparison is observational. Agents that verify may differ in ways that stratifying by issue does not capture.
- Each phase covers one harness and one model family: SWE-agent with three Llama-based action models from 2024, and
  Claude Code with gpt-oss-120b.
- Categories are computed by rules. A script that prints a wrong answer without raising counts as `ran_passing`.
- The 147 phase 2b issues are those where the agent skipped verification at least once in stage 1, so the pooled
  estimate describes those issues.

## License, sources and citation

CC BY 4.0. Phase 1 is derived from nebius/SWE-agent-trajectories (CC BY 4.0); its card asks users of the model
outputs to follow the Llama 3.1 license, and no model output is included here. Phase 2 uses SWE-bench Verified
instance ids and verifier results; that dataset's card declares no license, and none of its text is included.

```bibtex
@misc{peker2026doneclaims,
  title  = {done-claims: coding agents that submit without running anything after their last edit},
  author = {Peker, Serkan},
  year   = {2026},
  url    = {https://huggingface.co/datasets/serkanpeker/done-claims}
}
```
