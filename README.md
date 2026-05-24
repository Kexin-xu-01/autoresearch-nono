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
- [Node.js](https://github.com/nvm-sh/nvm) 18+ installed (via nvm recommended: `nvm install 18 && nvm alias default 18`)
- [Claude Code](https://claude.ai/code) installed (`curl -fsSL https://claude.ai/install.sh | bash`)
- [uv](https://docs.astral.sh/uv/) installed

---

## Quickstart

```bash
# 1. Clone this repo (includes the workload)
git clone https://github.com/Kexin-xu-01/autoresearch-nono
cd autoresearch-nono

# 2. Install nono registry packs
nono pull always-further/claude
nono pull Kexin-xu-01/claude-autoresearch

# 3. One-time: generate signing key and set up user-level trust policy
nono trust keygen --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust init --user --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust sign-policy "$HOME/.config/nono/trust-policy.json" --keyref "file://$HOME/.config/nono/trust-key.pem"

# 4. One-time: sign the program file for your chosen corpus (pick one)
cd workload

# Option A — IBD clinical cases (MultiCaRe)
nono trust init --include "ibd/program_ibd.md" --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust sign-policy --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust sign ibd/program_ibd.md --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust verify ibd/program_ibd.md

# Option B — TCGA multi-organ cancer pathology reports
nono trust init --include "tcga/program_tcga.md" --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust sign-policy --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust sign tcga/program_tcga.md --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust verify tcga/program_tcga.md

# Option C — climbmix general web text
nono trust init --include "climbmix/program.md" --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust sign-policy --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust sign climbmix/program.md --keyref "file://$HOME/.config/nono/trust-key.pem"
nono trust verify climbmix/program.md

cd ..

# 5. One-time: set up a dedicated SSH deploy key for the agent
#    The agent commits experiments to git, so it needs push access.
#    Use a separate key rather than your personal one.
ssh-keygen -t ed25519 -f ~/.ssh/autoresearch_github -C "autoresearch-agent" -N ""
#    Add ~/.ssh/autoresearch_github.pub to your GitHub repo as a deploy key with write access
#    (Settings → Deploy keys), then point the remote at SSH:
git remote set-url origin git@github.com:<your-username>/autoresearch-nono.git

# Each time before launching: load the deploy key into ssh-agent
eval $(ssh-agent -s) && ssh-add ~/.ssh/autoresearch_github

# 6. One-time: prepare data and train tokenizer for your chosen corpus (pick one)
cd workload && uv run ibd/prepare_ibd.py && cd ..    # Option A
cd workload && uv run tcga/prepare_tcga.py && cd ..  # Option B
cd workload && uv run climbmix/prepare.py && cd ..   # Option C

# 7. Launch — no path argument needed (launch.sh auto-detects the signed bundle)
./launch.sh
```

Once Claude starts, kick off the experiment with the message for your chosen corpus:

> **IBD**: Hi — have a look at ibd/program_ibd.md and let's kick off a new experiment! Let's do the setup first.

> **TCGA**: Hi — have a look at tcga/program_tcga.md and let's kick off a new experiment! Let's do the setup first.

> **Climbmix**: Hi — have a look at climbmix/program.md and let's kick off a new experiment! Let's do the setup first.

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

## Example results

After running overnight on IBD clinical case reports (MultiCaRe dataset), the agent ran 34 experiments and kept 18 improvements, reducing validation BPB from 1.09 to 0.76 — roughly a 30% reduction:

![Autoresearch results on IBD data](output.png)

Key changes the agent discovered: depth scaling, SwiGLU activations, grouped-query attention (GQA), and removal of value embeddings. Green dots are kept experiments; grey dots were tried and reverted; the step line tracks the running best.

---

## Files

```
workload/
  train.py               GPT model + training loop (the file the agent modifies)
  analysis.ipynb         experiment analysis and BPB progress chart
  pyproject.toml         Python dependencies
  uv.lock                dependency lock file
  .python-version        pinned Python version
  .claude/               Claude Code settings for the sandboxed session
  ibd/
    prepare_ibd.py       IBD data prep + tokenizer training (MultiCaRe IBD cases)
    corpus.py            IBD corpus loader
    program_ibd.md       agent instructions (IBD)
    program_ibd.md.bundle  signed attestation bundle (generated on first run)
  tcga/
    prepare_tcga.py      TCGA data prep + tokenizer training (multi-organ cancer pathology reports)
    corpus.py            TCGA corpus loader
    program_tcga.md      agent instructions (TCGA)
  climbmix/
    prepare.py           generic data prep (climbmix web text)
    corpus.py            climbmix corpus loader
    program.md           agent instructions (generic, climbmix)
profiles/
  claude-code-autoresearch.json  source of the nono registry pack (install via: nono pull Kexin-xu-01/claude-autoresearch)
trust/                   attestation bundles live here locally (not committed)
audit-examples/          add session excerpts here after runs
output.png               example results chart (IBD overnight run)
blog_concise.md          blog post write-up
launch.sh                sandbox launcher with attestation enforcement
```
