# done-claims

Coding agents often submit a change without running anything after their last edit. This repository
measures how often that happens and how it relates to whether the change resolves the issue.

- Phase 1 looks at 51,087 submitted SWE-agent runs from
  [nebius/SWE-agent-trajectories](https://huggingface.co/datasets/nebius/SWE-agent-trajectories).
  In 39.4% of the submissions that changed product code, nothing ran after the last edit. Within the
  same issue, their odds of resolving it were 0.68 times those of submissions whose last run after the
  edit showed no failure (95% CI 0.63 to 0.74, 598 issues).
- Phase 2b is pre-registered: Claude Code driven by gpt-oss-120b on SWE-bench Verified, 2,676 trials in
  two stages. Over the 147 issues where the agent skipped verification at least once, the within-issue
  odds ratio is 0.55 (95% CI 0.37 to 0.82, 73 issues), below 1 as the pre-registered rule requires.

[RESULTS.md](projects/done-claims/RESULTS.md) gives every number with its source, and [PLAN.md](projects/done-claims/PLAN.md) is the
pre-registration, written before each stage ran. The per-trajectory and per-trial results are also on
the Hugging Face Hub as [serkanpeker/done-claims](https://huggingface.co/datasets/serkanpeker/done-claims). No trajectory or transcript text is included.

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
