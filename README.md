# autoresearch-nono

Kernel-level sandboxing for [Karpathy's autoresearch](https://github.com/karpathy/autoresearch)
using [nono](https://github.com/lukehinds/nono).

autoresearch gives an AI agent autonomous write access to a training codebase and spawns GPU
training subprocesses overnight. nono uses Linux Landlock (or macOS Seatbelt) to enforce
filesystem and network restrictions at the kernel level — restrictions that cascade to all child
processes and cannot be bypassed. Unauthorized operations become structurally impossible, not
just filtered.

No modifications to the autoresearch workload are required.

---

## What nono adds

| Without nono | With nono |
|---|---|
| Agent can read `~/.aws`, `~/.ssh` | Blocked at kernel level |
| Agent can write to any file | Write access limited to repo + cache dirs |
| Training subprocess has full network access | Network restricted to LLM API + HuggingFace |
| No record of what the agent actually accessed | Structured audit log of every operation |
| `program.md` instructions can be silently modified | Tamper detection via Sigstore attestation |

---

## Prerequisites

- Linux kernel ≥ 5.13 (Landlock support) — or macOS 10.5+ for the MLX profile
- [nono](https://github.com/lukehinds/nono) installed
- [karpathy/autoresearch](https://github.com/karpathy/autoresearch) cloned separately

---

## Quickstart

```bash
# 1. Install the nono profile
cp profiles/autoresearch.json ~/.config/nono/profiles/

# 2. Sign program.md (one-time key generation + sign)
nono trust keygen
nono trust sign --keyed /path/to/autoresearch/program.md

# 3. Launch
./launch.sh /path/to/autoresearch
```

That's it. The agent runs exactly as it would standalone — except that the kernel now enforces
what it can and cannot touch.

---

## How the profile was derived

The profile in `profiles/autoresearch.json` was generated using `nono learn`:

```bash
cd /path/to/autoresearch
nono learn -- claude
```

Running 2-3 full experiment cycles (~20-30 min) captures the stable filesystem and network
footprint. The agent reads `program.md`, `train.py`, `prepare.py`, and `run.log` each cycle;
writes `train.py`, `run.log`, and `results.tsv`; and spawns `uv run train.py` as a subprocess.

Network-wise: Anthropic API for agent calls, HuggingFace CDN for the one-time dataset download,
PyPI via uv for package installs. No network during training itself.

The `deny_credentials` security group blocks `~/.aws`, `~/.ssh`, shell configs, and browser
credential stores by default, without needing to enumerate them.

### Child process inheritance

The most important property to verify: restrictions cascade to the training subprocess spawned
by `uv run train.py`. This is where application-level sandboxes fail. With nono's Landlock
enforcement, the child process inherits the same policy automatically.

---

## Attestation

`launch.sh` verifies `program.md` against a Sigstore bundle before each run. If `program.md`
is tampered with between runs (changing the agent's research mandate), the run aborts.

```bash
# Sign before first run
nono trust sign --keyed /path/to/autoresearch/program.md
# → produces program.md.bundle alongside program.md

# Tamper test: modify program.md without re-signing
echo "# tampered" >> /path/to/autoresearch/program.md
./launch.sh /path/to/autoresearch
# → [nono] ABORT: program.md attestation failed.
```

Bundles are generated locally and not committed to this repo (see `trust/.gitkeep`).

---

## Audit log

Every session is recorded by nono. Query after a run:

```bash
# List recent sessions
nono audit list --recent 5

# View full session details
nono audit show <session-id> --json

# Filter by operation type
nono audit show <session-id> --json | jq '.denials'
nono audit show <session-id> --json | jq 'select(.operation == "network")'
```

`audit-examples/` contains representative excerpts from clean runs and violation attempts.

### Git vs audit

git shows what the agent committed. nono shows what it actually touched, including reads and
network calls that left no git trace:

```bash
# git's view
git -C /path/to/autoresearch log --oneline

# nono's view of the same session
nono audit show <session-id> --json
```

---

## Apple Silicon (MLX)

For the [MLX fork](https://github.com/trevin-creator/autoresearch-mlx) on Apple Silicon,
use the Mac profile:

```bash
cp profiles/autoresearch-mlx.json ~/.config/nono/profiles/
# edit launch.sh: change --profile autoresearch to --profile autoresearch-mlx
./launch.sh /path/to/autoresearch-mlx
```

The MLX profile differs from the Linux profile in its security groups (`system_read_macos`
instead of `system_read_linux`) and the absence of CUDA library paths. The two profiles
side by side illustrate why `nono learn` exists: hand-writing policy across platforms doesn't
scale.

---

## Files

```
profiles/
  autoresearch.json      nono profile for Linux/CUDA
  autoresearch-mlx.json  nono profile for macOS/MLX (Apple Silicon)
trust/
  .gitkeep               program.md.bundle is generated locally, not committed
audit-examples/
  .gitkeep               add session excerpts here after Phase 2 runs
launch.sh                attestation check + nono run wrapper
```
