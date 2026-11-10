# done-claims

Working name; the public name is not decided. Status on 5 November 2026: phase 1 is done; the phase 2 full run (option 2 below, open models only) started at 22:07 and is expected to finish in the morning of 6 November.

Coding agents often say a task is finished without running anything after their last change. At least a dozen open-source hooks now try to stop this by checking the agent's closing message or its session log. The nine whose READMEs were read on 5 November 2026 report detection fixtures or false-positive tuning. None of them reports whether a "done" claim without evidence is actually wrong more often. This project measures that first and only then decides whether a tool is worth building.

The closest prior work, checked on the same day:

| Project | What it does | Measurement in the README |
|---|---|---|
| [qkal/Canny](https://github.com/qkal/Canny) | deterministic hooks that refuse "done" without evidence | none found |
| [VectorInstitute/backcheck](https://github.com/VectorInstitute/backcheck) | checks Claude Code claims against the session transcript, no LLM calls | none found |
| [godic97/claim-check](https://github.com/godic97/claim-check) | checks "tests pass", "build succeeds" and "lint is clean" claims against the commands that ran | none found |
| [vnmoorthy/groundtruth](https://github.com/vnmoorthy/groundtruth) | completion-claim gate for Claude Code | false-positive calibration on 1,272 turns |
| [waitdeadai/no-vibes](https://github.com/waitdeadai/no-vibes) | Stop hook that pattern-matches unearned success language | F1 0.815 on 19 labelled traces |
| [Nari-Ab/agent-roast](https://github.com/Nari-Ab/agent-roast) | blocks weakened tests and CI gates | rule hits on 12,645 commits in 166 repositories |
| [safety-research/impossiblebench](https://github.com/safety-research/impossiblebench) | measures how often agents exploit tests on impossible tasks | cheating rate per model |

Phase 1 is the measurement on 51,087 public SWE-agent submissions in [RESULTS.md](RESULTS.md). The classifier is deterministic and has 86 unit tests. The agent that wrote it audited it row by row on two random samples of 40 submissions; no human has reviewed those rows yet.

Phase 2 had three options, and the second was chosen:

1. Publish phase 1 as it is: this folder as a GitHub repository, the per-trajectory features as a Hugging Face dataset with no trajectory text, and a short article.
2. Replicate on current agents before publishing. Claude Code and Codex would run on public tasks, either with an API budget or with open models served on the 6×H200 measurement machine, and the same classifier would read their transcripts.
3. Build a checker only if the replication shows the same effect on current agents, or contribute the measurement to an existing checker instead.

Phase 2 replicates phase 1 with Claude Code driven by an open model on the 6×H200 machine. The design is fixed here, before any run:

- Harness: the unmodified Claude Code CLI inside [Harbor](https://github.com/harbor-framework/harbor) (Apache-2.0), with `ANTHROPIC_BASE_URL` pointing at a local vLLM server. Red Hat's [coding_agent_bench](https://github.com/redhat-et/coding_agent_bench) ran the same setup with Qwen3.6-35B on SWE-bench Verified: 63.2%, about 6 hours on 2×A100.
- Model: `openai/gpt-oss-120b` (Apache-2.0, already on the machine, vLLM tool parser `openai`). Qwen3.8-27B is the second model if time allows.
- Tasks: the 500 issues of SWE-bench Verified, three attempts each, so that within-issue comparisons have variation. Labels come from Harbor's verifier, which runs the hidden tests.
- Classifier: `doneclaims.atif` on each trial's `agent/trajectory.json`. Product files are the files the agent's applied edits touched.
- Hypotheses: (H1) the within-issue odds ratio for `unverified` against `ran_passing` is below 1; (H2) among `unverified` runs, a success claim in the closing message does not lower the odds of resolution; (H3) a test run after the edit does not beat a script run. The analysis is the same as in phase 1.
- Order: a 10-issue smoke run first, to check transcripts, rewards and the adapter on real output, then the full 1,500 trials.
- GPU work starts only after the P4 overnight measurements on the same machine finish, because a concurrent load would distort their latency numbers.

The smoke run on 5 November 2026 settled four details. They are written down here before the full run starts:

- Product files are the applied edit targets inside the repository working directory that Harbor records for the session (`/testbed`). Claude Code keeps its own memory notes under `/logs/agent/sessions/.../memory/`, and agents put throwaway scripts in `/tmp`; neither is product code. Paths are made relative to the repository, so `sed -i` on `pkg/core.py` and an `Edit` of `/testbed/pkg/core.py` are the same file.
- Harbor's SWE-bench tasks declare public network access, and one smoke trial used it to fetch a pastebin link. Closing the network would mean editing the benchmark's task files. Instead, each trial records how many shell commands reach a URL or a git remote, and H1 to H3 are computed again without those trials.
- A trial enters the analysis when the agent stopped on its own and the verifier wrote a reward. Trials that end in a Harbor exception, such as an agent timeout, are counted and reported but not classified, just as phase 1 kept only submitted runs.
- Harbor sends the key as a bearer token only when the variable it reads the key from is called `ANTHROPIC_AUTH_TOKEN`. The first smoke attempt used another name, every model request was rejected with 401, and that attempt was discarded.

One change departs from the design above. Harbor gives the agent the bare issue text, with no request to change anything. In the smoke run, gpt-oss-120b stopped on its own in 9 of 10 trials, and in 6 of those it edited no file: it explained the issue and stopped. Those trials carry no information about verification. The full run therefore appends one sentence to every issue: "Resolve the issue above by changing the code in the repository in your current working directory." The sentence does not mention tests, running code or checking the result. On the same 10 issues, with the sentence, all 10 trials changed product code and 5 resolved the issue: 5 ended `ran_failing`, 2 `ran_passing` and 3 `unverified`. Serkan chose this option over two alternatives: running Qwen3.8-27B unchanged, which needed 30 to 50 minutes per trial at its default `xhigh` reasoning effort, or keeping gpt-oss without the sentence. Qwen3.8-27B remains the second model once it is faster.

Trials that fail for infrastructure reasons are run again, not classified. These are a Claude Code install that hits Harbor's 360-second setup limit, which happened to 10 trials when 32 started at once; a task container that does not come up; and a model server error. A trial in which the agent itself runs past the 50-minute limit is kept and reported as an exception.

## Phase 2b, pre-registered on 8 November 2026

Phase 2a finished all 1,500 trials, but its environment blurs what a run shows: the agent's shell used the image's base Python 3.11 instead of the task's environment, so runs often failed on missing modules, and `ran_failing` and `ran_passing` resolved at the same rate (see RESULTS.md). Its within-issue estimate also rests on 22 issues. Four auditor agents built on different models and the coordinator agreed on the design below (decision record #26). It is fixed here before stage 1 starts.

Conditions. Everything as in phase 2a (Claude Code 2.1.318, Harbor 0.25.0, `openai/gpt-oss-120b` on vLLM 0.33.0 with the same image digest, SWE-bench Verified, the same appended sentence), with four changes:

- The agent's `PATH` starts with the task's environment, `/opt/miniconda3/envs/testbed/bin`, which is what the verifier activates. A live check during the smoke run showed the Claude Code process and its shell snapshot resolving `python` to the task's interpreter (3.6, 3.8 or 3.9 depending on the task).
- Claude Code comes from a prebuilt binary of the same version (SHA-256 prefix `708c77b204db3008`), mounted read-only at `/root/.local/bin/claude`; Harbor then skips its per-container apt and npm install, which saturated the disk in phase 2a. The auto-updater is off.
- 12 trials run at once instead of 16.
- Claude Code is told the model's real context window (`CLAUDE_CODE_MAX_CONTEXT_TOKENS=131072`, the vLLM limit). Without it Claude Code assumes 200K for an unknown model and compacts too late: in the smoke run, 2 of 29 finished trials grew past the server's limit and ended in an API error, which counts as an infrastructure failure and is rerun, so long sessions would drop out of the sample. With the setting, 5 trials on the same two issues finished without an overflow, two of them after a compaction. This fourth change was added after the smoke run and before stage 1.

Smoke gates. 10 issues drawn with seed 20261108, 3 attempts each. All must hold before stage 1: no setup timeout; the agent's interpreter is the task's; at least 8 `ran_failing` trials, of which at least 80% end on a test failure rather than a missing module or command (if fewer than 8 occur, the smoke grows to 20 issues); among `ran_passing` trials with a test run, at least half show an explicit pass. If the gates fail, the environment is fixed once more and the smoke repeated; if they fail again, the decision goes back to Serkan.

Smoke result, 8 November 2026. The first 10 issues gave 6 `ran_failing` trials, so the smoke grew by 10 issues drawn with seed 20261109 (the extension ran with the context setting). Over the 59 finished trials all gates held: no setup timeout; no transcript mentions the base Python 3.11 path, 2,779 mention the task's environment; 14 `ran_failing` trials, 12 of them (86%) ending on a failing test, script or test command rather than a missing module or command (the other two found `pytest` absent from the django and sympy task environments); 10 of 15 `ran_passing` trials with a test run show an explicit pass. Reading the 14 by hand also showed what the gate counts as a test failure: the agent's own mistakes (Django tests run through `unittest` without settings, a selector matching 0 tests) and one classifier error, a script that finished cleanly but printed a traceback Python ignored at exit, which the frozen rules read as a failure. The stage-1 audit measures how often that happens. 8 of 52 trials that changed product code were `unverified` (15%).

Server change during stage 1, 8 November. Stage 1 started at 17:01 with the model on one GPU, as in phase 2a. That GPU stayed busy: about 8 of the 12 trials were waiting for the model at any moment. At 18:00 the server was restarted with tensor parallelism across two GPUs; model, image, seed and every agent setting stayed the same. 38 trials had finished on the one-GPU server (37 completed, 1 agent timeout), all with their agent done before the job was stopped; the 12 trials cut off by the restart were cancelled and run again. A faster server changes how many agent steps fit into the 50-minute limit, so the main estimates are also reported without those 38 trials. At 21:00 the host's write-back throttling (`wbt_lat_usec`) was turned off: agents running Django's whole suite push their 4 GB task containers into swap, and most blocked processes were waiting in the throttle while the disk itself answered within 3 ms. This changes disk speed for every trial, not what the agent can run.

Stage 1. All 500 issues, 3 attempts each, classified by `doneclaims` with the SHA-256 recorded below. Infrastructure failures are rerun.

Gate between stages. If `unverified` is below 8% of stage-1 trials that changed product code, stage 2 does not run and phase 2b is reported as a description.

Stage 2. Every issue with at least one completed `unverified` stage-1 attempt gets k more attempts. `python -m doneclaims.power` (seed 20261108, true odds ratio 0.68 as in phase 1, 300 simulations per k) fits the stage-1 trials and picks k as the smallest even value from 2 to 12 for which at least 90% of simulations give upper/estimate at most 1.5; if none does, k is 12. k is written here before stage 2 starts. All k attempts run; there is no stopping on results. Infrastructure failures are rerun.

Stage 1 result and stage 2 parameters, 9 November 2026, written before stage 2 starts.

- Stage 1 ended at 15:52: 1,500 trials, 1,437 completed (839 resolved), 63 exceptions (56 agent timeouts, 5 verifier timeouts, 1 missing reward file, 1 non-zero agent exit).
- Code change. The frozen classifier crashed on one tool call: in `sphinx-doc__sphinx-8595__L6UJQVE` the agent sent a Bash call whose `command` was a JSON array, and Claude Code rejected it at input validation ("The parameter `command` type is expected as `string` but provided as `array`"), so nothing ran. `doneclaims.atif` now treats a shell call with a non-string command as a rejected call that is neither an edit nor a run, with a unit test. No other stage-1 call has a non-string command. SHA-256 of the `doneclaims` sources after the change: `c0b6a8c4cc16d230c448af82ad223cafbcd0f7d26d579cc3d18747b57c136420`; every phase 2b number is reported with this version.
- Gate: 191 of the 1,407 completed trials that changed product code are `unverified` (13.6%), above 8%, so stage 2 runs.
- `doneclaims.power` (seed 20261108, odds ratio 0.68, 300 simulations) on the stage-1 trials: 147 issues have at least one completed `unverified` attempt; the share of simulations with upper/estimate at most 1.5 is 0.00, 0.01, 0.50, 0.97, 1.00 and 1.00 for k = 2 to 12. k = 8: 1,176 stage-2 trials. The issue list is `results/phase2b/stage2_issues.txt`.
- Committed result files name trials `<instance_id>__s1-NN` (stage 2: `s2-NN`), numbered per issue in the order of Harbor's names (`phase2/alias_trials.py`); the mapping to Harbor's random names stays in the local cache. One random suffix spelled a string the repository's privacy scan blocks. Classification and statistics are unchanged.
- Stage 2 conditions are the stage-1 conditions unchanged: 12 trials at once, gpt-oss-120b on two GPUs with tensor parallelism, task containers on CPUs 0–95, the same image, binary, appended sentence and context setting. Raising concurrency was considered and dropped. During stage 1 the model was not the bottleneck (1 to 4 requests running, none waiting), while agents running Django's test suite pushed the host's CPU pressure to 66% and its load average to about 990; agent timeouts rose to 56 from 17 in phase 2a. More trials at once would add CPU contention and timeouts, and stage-1 and stage-2 attempts of the same issue are pooled in the primary analysis.

Stage 2 run and audit plan, 10 November 2026, written before the pooled analysis is run.

- Stage 2 ran from 9 November 18:19 to 10 November 17:06: 1,176 trials, 1,103 completed, 73 exceptions (69 agent timeouts, 3 missing reward files, 1 verifier timeout); no retryable trial was left. Classified with the `doneclaims` version `c0b6a8c4…` above.
- On 10 November 13:16 the watcher paused the job for a quiet measurement by another project on the same machine: the 16 running trials were cut off and their containers removed, the model server was stopped, and the job resumed at 14:04 on a fresh server with the same model, image and settings. The cut-off trials ran again as infrastructure failures. Nothing else changed.
- Audit before any number is reported: two random samples of 40 completed stage-1 trials, 10 per category, drawn by `doneclaims.audit_harbor` with seeds 20261110 and 20261111 (2 trials are in both). Two auditor agents built on different model families read all 80 rows independently against the definitions (brief kept with the views, outside git); every row that either of them does not call correct is read again by the agent that wrote the classifier, which records the final verdict and its reason. A human re-check of the 80 rows stays with Serkan.

Primary analysis (H1). `python -m doneclaims.phase2b`: over the stage-2 issue set, the Mantel-Haenszel odds ratio of resolution for `unverified` against `ran_passing`, strata = issue, stage-1 and stage-2 trials pooled, with the Robins-Breslow-Greenland 95% interval. H1 counts as supported only if the upper end is below 1. With phase 1's effect (0.68), the simulation on phase 2a data puts the chance of that near 0.6 at k = 10; 80% power would take more than 5,000 trials and is outside the budget, so H1 is an estimation target and the interval is reported as it falls.

Secondary analyses, reported whatever their direction: the stage-1 estimate over all issues; `ran_failing` against `ran_passing`; H2, a success claim among `unverified` trials; H3, a test run against a script only among `ran_passing` trials; every estimate again without trials that fetched from the network; resolution after an explicit pass against a run with no failure signal. The classifier is audited by hand on two random samples of 40 stage-1 trials before anything is reported.

Code fixed for phase 2b: SHA-256 of the `doneclaims` sources `7710e6c1255ae8a879b033df6f3643dc896d9bea07b3bebb9b837b28a031674d`, as computed by `doneclaims.study.code_digest`. A change after this point is listed here with its reason, and every phase 2b number is reported with the code version it came from.

Two things are out of scope. One is another hook that matches closing-message language, since in the SWE-agent runs that language did not separate failed submissions from the rest. The other is redistributing trajectory text or putting OpenAI, Anthropic or Google outputs into any dataset.

Decisions for Serkan, taken on 10 November 2026 (decision record #35):

- the public name is done-claims; the GitHub repository `speker/done-claims` and the Hugging Face dataset
  `serkanpeker/done-claims` open publicly, code under MIT and results under CC BY 4.0;
- instead of a human re-check of the 80 audited rows, a jury of four language models from different families
  (GPT-5.6 Sol, Gemini 4 Argon, Grok 4.7, Muse Wonder 1.0) re-reads all 80 rows without seeing the earlier
  verdicts, with the full output of every run after the last product edit. No human has re-checked the rows.

The phase 2 budget question is settled: open models only, no API spend (5 November 2026).

The effect may be smaller for 2026 agents than for the 2024 Llama-based SWE-agent runs measured here. A write-up that mentions other checkers can also read as criticism, so phase 1 measures agent behaviour and does not rank any tool.
