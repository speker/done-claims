# done-claims

This repository measures how often coding agents submit a change without running a test or script after
their last edit, and how that relates to whether the change resolves the issue.

- Phase 1 looks at 51,087 submitted SWE-agent runs from
  [nebius/SWE-agent-trajectories](https://huggingface.co/datasets/nebius/SWE-agent-trajectories).
  In 39.4% of the submissions that changed product code, no test or script ran after the last edit.
  Within the same issue, their odds of resolving it were 0.68 times those of submissions whose last run
  after the edit showed no failure (95% CI 0.63 to 0.74, 598 issues).
- Phase 2a ran Claude Code driven by gpt-oss-120b on SWE-bench Verified, 1,500 trials. The within-issue
  odds ratio, 1.04 (95% CI 0.42 to 2.55, 22 issues), is inconclusive.
- Phase 2b repeats it in two stages, 2,676 trials, with its hypothesis and decision rule set in a dated
  plan. Over the 147 issues where the agent skipped verification at least once, the within-issue odds
  ratio is 0.55 (95% CI 0.37 to 0.82, 73 issues); the upper end is below 1, which is the plan's rule.

[RESULTS.md](projects/done-claims/RESULTS.md) gives every number with its source. [PLAN.md](projects/done-claims/PLAN.md) is the plan,
dated before each stage ran; it is a file in this repository, not an entry in a public registry. The
per-trajectory and per-trial results are also on the Hugging Face Hub as [serkanpeker/done-claims](https://huggingface.co/datasets/serkanpeker/done-claims).
No trajectory or transcript text is included. The write-up is the article
[Coding agents that submit without running a test or script](https://huggingface.co/blog/serkanpeker/done-claims) ([Türkçe](https://huggingface.co/blog/serkanpeker/kanitsiz-bitti)).

## Reproduce

```bash
uv sync
cd projects/done-claims
uv run python -m doneclaims.fetch          # phase 1 data, 12 Parquet shards
uv run python -m doneclaims.study --workers 6
uv run python -m unittest discover -s tests -t .
uv run python -m doneclaims.phase2b \
    results/phase2b/p2b-stage1/trials.csv results/phase2b/p2b-stage2/trials.csv
```

Phase 2 ran on a GPU machine with the scripts in `projects/done-claims/phase2/` (vLLM, Harbor, Claude Code); RESULTS.md
lists the versions and the steps. Transcripts stay out of the repository.

## License

Code: MIT, see `LICENSE`. Results under `projects/done-claims/results/`: CC BY 4.0, see `LICENSE-results`. Phase 1
results are derived from nebius/SWE-agent-trajectories (CC BY 4.0); its card asks users of the model
outputs to follow the Llama 3.1 license, and no model output is redistributed here.
