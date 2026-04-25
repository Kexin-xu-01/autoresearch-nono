# Running an AI agent overnight on medical text

Last month I set up Andrej Karpathy's autoresearch to run overnight on medical pathology text. The premise is straightforward: give an AI agent a training script, a fixed time budget, and a goal metric, then let it experiment while you sleep. By morning you have a run of experiments charted, the agent having tried architectural changes, learning rate schedules, and batch size sweeps that would take much longer to work through manually.

I have been interested in training language models on medical text as a hobby — specifically building models that understand the language of clinical reports well enough to assist with reading them. To demonstrate the setup, I used two publicly available corpora: IBD clinical case reports from the [MultiCaRe dataset](https://zenodo.org/records/10079370) (96,000+ open-access PMC case reports), and TCGA cancer pathology reports. Domain-specific pretraining requires substantial iteration over interdependent choices — vocabulary size, context window, model depth — and autoresearch makes that iteration feasible to run unattended.

However, running an AI agent autonomously overnight on a personal machine raises a security concern that I wanted to address before relying on it.

---

## The security problem

Autoresearch's security model is behavioural: the agent stays on task because it has been instructed to. For interactive use this is a reasonable assumption, but for an unattended overnight run it is the only control in place. The relevant risk is not limited to the agent process itself.

During a session, autoresearch: reads `ibd/program_ibd.md` (the instruction file); calls the LLM API; writes changes directly to `train.py`; spawns a GPU training subprocess that runs for five minutes; then reads the log output, evaluates the metric, and commits or resets. The agent therefore has unrestricted write access to the codebase, and the training subprocess it spawns runs arbitrary Python with full network access — on a machine that holds `~/.aws` credentials for the GPU instance and `~/.ssh` keys for the cluster.

If the agent behaves unexpectedly — through a model quirk, an adversarial prompt, or content in the training data — there is no structural barrier preventing it from accessing credential paths or making network calls that would be indistinguishable from legitimate traffic. More critically, application-level filtering only covers the agent process itself; the training subprocess it spawns is outside that perimeter entirely.

---

## Why nono

[nono](https://github.com/lukehinds/nono) is a sandbox for AI agents built on Linux Landlock (kernel 5.13+) and macOS Seatbelt, enforcing filesystem and network restrictions at the syscall level. The key property for this use case is child process inheritance: restrictions applied to the agent cascade automatically to every process it spawns. The training subprocess therefore operates under the same constraints as the agent, with no additional configuration required.

Most application-level sandboxes do not have this property — they constrain the agent but leave spawned subprocesses uncovered. nono's kernel-level enforcement closes that gap.

Building the profile started with `nono learn`, which observes a real process and generates a policy from its actual footprint. That gave a reasonable base, but GPU access required trial and error — CUDA, Triton, and the NVIDIA driver touch paths that are not obvious until something breaks.

---

## What the profile enforces

The `claude-code-autoresearch` profile extends nono's base `claude-code` profile and adds GPU access. It allows read/write access to:

- The autoresearch-nono repo directory
- `~/.cache/autoresearch/` — training data and tokenizer
- `~/.cache/torch`, `~/.cache/huggingface` — framework caches
- `~/.cache/uv`, `~/.local/share/uv` — package manager cache
- `~/.nv`, `~/.triton/cache` — GPU compilation caches
- `/tmp`, `/dev/shm`, `/proc` — runtime requirements

Credential paths (`~/.aws`, `~/.ssh`) are absent from the allow list and are therefore blocked. Network access is restricted to the LLM API and HuggingFace. Both constraints are inherited by the training subprocess.

| Without nono | With nono |
|---|---|
| Agent can read `~/.aws`, `~/.ssh` | Blocked at kernel level |
| Agent can write to any file | Write access limited to repo + cache dirs |
| Training subprocess has full network access | Network restricted to LLM API + HuggingFace |
| No record of what the agent actually accessed | Structured audit log of every operation |
| `program_ibd.md` can be silently modified | Tamper detection via Sigstore attestation |

---

## Audit log

Beyond the security properties, the nono audit log provides observability that git alone does not. git records what the agent committed; nono records what it actually accessed — every filesystem read and write, every network call, and every denied operation. These are different records: an agent that reads `~/.ssh` and does nothing with it leaves no git trace, but it appears in the nono audit.

```bash
# git's view — what was committed
git -C workload log --oneline autoresearch-nono/apr25b

# nono's view — what was actually touched
nono audit show <session-id> --json | jq '.denials'
```

For a research context this is independently useful: it allows me to confirm which data shards were accessed during evaluation, verify that the training subprocess is only reaching expected network endpoints, and identify unexpected behaviour in the CUDA compilation layer.

---

## Attestation

Each corpus has its own instruction file: `ibd/program_ibd.md` for IBD, `tcga/program_tcga.md` for cancer pathology reports, and `climbmix/program.md` for general web text. These files specify the research question, the goal metric, what the agent may and may not modify, and how to log results.

If `program_ibd.md` is modified between runs — through a stale git state, a merge error, or anything else — the agent executes under a different mandate without any visible indication until the results are examined. nono's attestation layer addresses this using DSSE signed payloads with local key management. The program file is signed before the first run, and the launch script verifies the signature before starting the agent. If verification fails, the run aborts:

```
[nono] Checking attestation...
[nono] ABORT: attestation failed — program_ibd.md may have been tampered with.
```

---

## Launch wrapper

`launch.sh` locates the signed attestation bundle for the chosen corpus, verifies it, then launches Claude Code under enforcement:

```bash
exec nono run \
    --profile claude-code-autoresearch \
    --allow-gpu \
    --allow-cwd \
    --workdir "${AUTORESEARCH_DIR}" \
    -- claude --dangerously-skip-permissions
```

`--dangerously-skip-permissions` is intentional. Autoresearch requires the agent to operate without interactive confirmation — that is the design. Claude Code's permission prompts and nono's kernel enforcement address different problems; for an unattended overnight run, the latter is the appropriate control.

---

## Getting started

The profile will be available via the nono profile registry. In the meantime it is in the `profiles/` directory of [autoresearch-nono](https://github.com/Kexin-xu-01/autoresearch-nono), along with three workloads (IBD, TCGA, climbmix), data preparation scripts, and the launch wrapper. The design intention was for nono to be a drop-in addition: the agent is unaware of the sandbox, and nothing in the training pipeline requires modification.

---

*The companion repo is at [github.com/Kexin-xu-01/autoresearch-nono](https://github.com/Kexin-xu-01/autoresearch-nono). The profile will be published to the nono registry shortly.*
