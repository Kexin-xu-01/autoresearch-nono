# autoresearch — TCGA surgical pathology reports

This is an autoresearch experiment: train a small GPT on TCGA surgical pathology
reports and autonomously improve it. The task is identical to the base autoresearch
setup — only the training corpus has changed (TCGA GI cancer pathology reports
instead of climbmix).

## Data setup (one-time, done by the human before starting)

```bash
# From autoresearch-nono/workload/
uv run tcga/prepare_tcga.py   # downloads TCGA corpus, trains tokenizer

# Verify data exists
ls ~/.cache/autoresearch/tcga/data/
ls ~/.cache/autoresearch/tcga/tokenizer/
```

If either directory is missing, stop and tell the human.

---

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `apr11`). The branch `autoresearch-nono/<tag>` must not already exist in the `autoresearch-nono` repo — this is a fresh run.
2. **Create the branch**: from the repo root (`autoresearch-nono/`), run `git checkout -b autoresearch-nono/<tag>` from `main`, then `git push -u origin autoresearch-nono/<tag>`. All experiment commits go into `Kexin-xu-01/autoresearch-nono`.
3. **Update the import in train.py**: change the `sys.path.insert` line to point to `tcga/` instead of `ibd/`:
   ```python
   sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tcga"))
   ```
4. **Read the in-scope files**: Read these files for full context:
   - `tcga/prepare_tcga.py` — fixed constants, data prep, tokenizer, dataloader, evaluation. Do not modify.
   - `train.py` — the file you modify. Model architecture, optimizer, training loop.
5. **Verify data exists**: Check that `~/.cache/autoresearch/tcga/` contains data shards and a tokenizer. If not, stop and tell the human to run the data setup steps above.
6. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
7. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

---

## Experimentation

Each experiment runs on a single GPU. The training script runs for a **fixed time budget of 5 minutes** (wall clock training time, excluding startup/compilation). Launch it as: `uv run train.py`.

**What you CAN do:**
- Modify `train.py` — this is the only file you edit. Everything is fair game: model architecture, optimizer, hyperparameters, training loop, batch size, model size, etc.

**What you CANNOT do:**
- Modify `tcga/prepare_tcga.py`. It is read-only. It contains the fixed evaluation, data loading, tokenizer, and training constants (time budget, sequence length, etc).
- Install new packages or add dependencies. You can only use what's already in `pyproject.toml`.
- Modify the evaluation harness. The `evaluate_bpb` function in `tcga/prepare_tcga.py` is the ground truth metric.

**The goal is simple: get the lowest val_bpb.** Since the time budget is fixed, you don't need to worry about training time — it's always 5 minutes. Everything is fair game: change the architecture, the optimizer, the hyperparameters, the batch size, the model size. The only constraint is that the code runs without crashing and finishes within the time budget.

**VRAM** is a soft constraint. Some increase is acceptable for meaningful val_bpb gains, but it should not blow up dramatically.

**Simplicity criterion**: All else being equal, simpler is better. A 0.001 val_bpb improvement that adds 20 lines of hacky code? Probably not worth it. Removing something and getting equal or better results? A simplification win — keep it.

**The first run**: Always establish the baseline first — run the training script as-is.

---

## Output format

Once the script finishes it prints a summary like this:

```
---
val_bpb:          0.997900
training_seconds: 300.1
total_seconds:    325.9
peak_vram_mb:     45060.2
mfu_percent:      39.80
total_tokens_M:   499.6
num_steps:        953
num_params_M:     50.3
depth:            8
```

Extract the key metric:

```bash
grep "^val_bpb:" run.log
```

---

## Logging results

Log to `results.tsv` (tab-separated, NOT comma-separated):

```
commit	val_bpb	memory_gb	status	description
```

1. git commit hash (short, 7 chars)
2. val_bpb achieved — use 0.000000 for crashes
3. peak memory in GB, .1f (divide peak_vram_mb by 1024) — use 0.0 for crashes
4. status: `keep`, `discard`, or `crash`
5. short description of what this experiment tried

Do not commit `results.tsv` — leave it untracked.

---

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoresearch-nono/apr11`).

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on
2. Tune `train.py` with an experimental idea by directly hacking the code.
3. git commit
4. Run the experiment: `uv run train.py > run.log 2>&1` (redirect everything — do NOT use tee or let output flood your context)
5. Read out the results: `grep "^val_bpb:\|^peak_vram_mb:" run.log`
6. If the grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the Python stack trace and attempt a fix. If you can't get things to work after more than a few attempts, give up.
7. Record the results in the tsv (NOTE: do not commit the results.tsv file, leave it untracked by git)
8. If val_bpb improved (lower), you "advance" the branch, keeping the git commit, then `git push origin autoresearch-nono/<tag>`.
9. If val_bpb is equal or worse, you git reset back to where you started

**Timeout**: Each experiment should take ~5 minutes total. If a run exceeds 10 minutes, kill it and treat it as a failure.

**NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue. You are autonomous. Run until manually stopped.

---

## TCGA task context

The corpus is TCGA surgical pathology reports:
- **TCGA-Reports**: 9,523 surgical pathology reports from The Cancer Genome Atlas
- GI tract cases: COAD (colon adenocarcinoma) and READ (rectal adenocarcinoma)
- Source: Kefeli et al., 2024 — Mendeley Data, CC BY 4.0

The text is structured pathology report language — gross descriptions, microscopic
assessments, diagnoses. Expect dense medical terminology and structured formatting.

Interesting angles to explore:
- Does a smaller vocab size help (pathology reports have constrained vocabulary)?
- Does a longer context window help (reports can be multi-section)?
- Does a deeper vs. wider model trade-off differ from general text?
