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
- `gnome-keyring` installed: `sudo apt install -y gnome-keyring`

---

## Quickstart

Replace `/path/to/autoresearch` with your actual clone path (e.g. `~/autoresearch`).

### Step 1 — install the nono profile

```bash
cp profiles/autoresearch.json ~/.config/nono/profiles/
```

### Step 2 — one-time signing setup

> **Desktop (GNOME/KDE/macOS):** run these directly:
> ```bash
> nono trust keygen
> cd /path/to/autoresearch
> nono trust init --include "program.md" --key default
> nono trust sign-policy
> nono trust sign --key default program.md
> ```

> **Headless servers (JupyterHub, SSH, cloud VMs):** the keyring requires its own
> D-Bus session. Run this single command (replace the path):

```bash
dbus-run-session -- bash -c 'echo "" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null; sleep 1 && nono trust keygen --force && cd /path/to/autoresearch && nono trust init --include "program.md" --key default --force && nono trust sign-policy && nono trust sign --key default program.md'
```

This produces `trust-policy.json`, `trust-policy.json.bundle`, and `program.md.bundle` in your autoresearch directory.

### Step 3 — launch

```bash
cd /path/to/autoresearch-nono
./launch.sh /path/to/autoresearch
```

`launch.sh` automatically handles the keyring session on headless servers — no manual `dbus-run-session` needed for day-to-day use.

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

`launch.sh` verifies `program.md` against its bundle before each run. If `program.md` is
tampered with between runs, the run aborts.

```bash
# Tamper test
echo "# tampered" >> /path/to/autoresearch/program.md
./launch.sh /path/to/autoresearch
# → [nono] ABORT: program.md attestation failed.
```

To re-sign after intentionally updating `program.md`:

```bash
dbus-run-session -- bash -c 'echo "" | gnome-keyring-daemon --unlock --components=secrets &>/dev/null; sleep 1 && cd /path/to/autoresearch && nono trust sign --key default program.md'
```

Bundles are generated locally and not committed to this repo (see `.gitignore`).

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

---

## Files

```
profiles/
  autoresearch.json      nono profile for Linux/CUDA
  autoresearch-mlx.json  nono profile for macOS/MLX (Apple Silicon)
trust/
  .gitkeep               trust-policy.json.bundle generated locally, not committed
audit-examples/
  .gitkeep               add session excerpts here after runs
launch.sh                attestation check + nono run wrapper (headless-aware)
```
