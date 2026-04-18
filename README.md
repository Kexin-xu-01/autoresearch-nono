# autoresearch-nono

Kernel-level sandboxing for [autoresearch](https://github.com/karpathy/autoresearch)
using [nono](https://github.com/lukehinds/nono). This repo bundles both the sandbox
configuration and the IBD-specialised training workload in one place.

autoresearch gives an AI agent autonomous write access to a training codebase and spawns GPU
training subprocesses overnight. nono uses Linux Landlock (or macOS Seatbelt) to enforce
filesystem and network restrictions at the kernel level — restrictions that cascade to all child
processes and cannot be bypassed. Unauthorized operations become structurally impossible, not
just filtered.

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

---

## Quickstart

```bash
# 1. Clone this repo (includes the workload)
git clone https://github.com/Kexin-xu-01/autoresearch-nono
cd autoresearch-nono

# 2. Install the nono profile
cp profiles/claude-code-autoresearch.json ~/.config/nono/profiles/

# 3. One-time: sign program.md (required — launch.sh will abort without this)
cd workload
nono trust keygen
nono trust init --include "program.md" --key default
nono trust sign-policy
nono trust sign --key default program.md
cd ..

# 4. One-time: prepare IBD data and train tokenizer
cd workload && uv run prepare_ibd.py && cd ..

# 5. Launch — no path argument needed
./launch.sh
```

That's it. The sandbox enforces filesystem and network restrictions regardless of whether
attestation is configured. To use a different autoresearch clone, pass its path:
```bash
./launch.sh /path/to/other-autoresearch-clone
```

---

## Attestation setup (required)

`launch.sh` will refuse to start unless `program.md` has been signed. This prevents the agent
from running with tampered instructions.

```bash
cd autoresearch-nono/workload

# One-time: generate signing key
nono trust keygen

# Initialise trust policy
nono trust init --include "program.md" --keyref "file://$HOME/.config/nono/trust-key.pem" --force

# Sign the policy and program.md
nono trust sign-policy --keyref "file://$HOME/.config/nono/trust-key.pem" trust-policy.json
nono trust sign --keyref "file://$HOME/.config/nono/trust-key.pem" --all
```

To re-sign after intentionally editing `program.md`:

```bash
cd autoresearch-nono/workload
nono trust sign --keyref "file://$HOME/.config/nono/trust-key.pem" --all
```

### Tamper detection

```bash
echo "# tampered" >> workload/program.md
./launch.sh
# → [nono] ABORT: attestation failed — program.md may have been tampered with.
```

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
workload/
  train.py               GPT model + training loop (the file the agent modifies)
  prepare.py             generic data prep (climbmix web text)
  prepare_ibd.py         IBD-specific data prep (TCGA + MultiCaRe)
  program.md             agent instructions (generic)
  program_ibd.md         agent instructions (IBD)
  trust-policy.json      attestation policy
  pyproject.toml         Python dependencies
  .claude/               Claude Code settings for the sandboxed session
profiles/
  claude-code-autoresearch.json  nono profile for Linux/CUDA + GPU
  autoresearch-mlx.json          nono profile for macOS/MLX (Apple Silicon)
showcase/
  prepare_ibd.py         simplified reference version of data prep
  program_ibd.md         reference program instructions
trust/
  .gitkeep               attestation bundles are generated locally, not committed
audit-examples/
  .gitkeep               add session excerpts here after runs
launch.sh                sandbox launcher with graceful attestation fallback
```
