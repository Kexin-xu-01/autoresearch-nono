# Running an AI agent overnight on medical text

Last month I set up Andrej Karpathy's autoresearch to run overnight on medical pathology text. The idea: give an AI agent a training script, a fixed time budget, and a metric to optimise, then let it experiment while you sleep. By morning, you have dozens of experiments charted — architectural changes, learning rate schedules, batch size sweeps — that would take weeks to work through manually.

I am a third-year PhD student in Computational Biology, working on applying AI to inflammatory bowel disease (IBD). Alongside that, I am interested in multi-agent AI for scientific research — which led me to join Always Further as an AI Researcher in February 2026. Autoresearch is a concrete example of that: an AI agent running autonomously on a scientific workload. To demonstrate the setup, I used two publicly available medical corpora: IBD clinical case reports from the [MultiCaRe dataset](https://zenodo.org/records/10079370), and surgical pathology reports from [TCGA](https://data.mendeley.com/datasets/hyg5xkznpx/1) (The Cancer Genome Atlas). Medical text differs substantially from the general text most AI models are trained on — clinical reports are dense with abbreviations, disease-specific terminology, and structured formats that general web text does not adequately cover, making training on domain-specific text worthwhile.

But before I let it run unattended overnight, I needed to think about what I was actually leaving running on my machine.

---

## The problem

Autoresearch gives the AI agent full access to write code, run it, and repeat — in a loop, all night. The agent modifies `train.py`, kicks off a training job that runs for five minutes, checks if the results improved, and either keeps the change or reverts it.

The part that gave me pause: the training job it launches runs with full internet access, on a machine that also has my cloud credentials and SSH keys sitting on it. The agent will behave because it has been told to — but that is the only guarantee. If something goes wrong, there is nothing technically stopping it from accessing files it should not, or making network calls that look like normal traffic. More critically, any application-level controls only cover the agent process itself; the training subprocess it spawns runs entirely outside that perimeter.

---

## Why nono

[nono](https://github.com/lukehinds/nono) is a tool that puts hard limits on what an AI agent is allowed to do at the operating system level — not just by telling it what not to do, but by making those actions technically impossible. It is built on Linux Landlock (kernel 5.13+) and macOS Seatbelt, enforcing restrictions at the syscall level.

The key property for this use case is child process inheritance: restrictions applied to the agent cascade automatically to every process it spawns. So when autoresearch kicks off a training job, that job runs under the same constraints as the agent itself — with no additional configuration. Most application-level sandboxes do not have this property. nono's kernel-level enforcement closes that gap.

I started with `nono learn`, which watches a real run and automatically figures out what files and network access the process actually needs. That gave a good starting point, but getting GPU training to work required a fair amount of trial and error — the GPU software stack touches a lot of places that are not obvious until something breaks.

| Without nono | With nono | How |
|---|---|---|
| Agent can read my cloud credentials and SSH keys | Blocked | `~/.aws`, `~/.ssh` absent from `allow` list; Landlock blocks at syscall level, not application level |
| Agent can write to any file on the machine | Write access limited to the project folder | `allow` covers repo dir + ML cache dirs only (`~/.cache/torch`, `~/.cache/huggingface`, `~/.nv`, etc.) |
| Training job has full internet access | Network limited to the AI API and HuggingFace | Network policy is inherited by child processes — the training subprocess gets no separate allowance |
| No record of what the agent actually did | Full log of every file and network access | nono audit log captures every syscall — reads, writes, network calls, and denials |
| Instruction file can be quietly changed | Verified before every run | `program.md` is DSSE-signed with a local key; `launch.sh` verifies the bundle before starting the agent |

---

## What the profile enforces

The `claude-code-autoresearch` profile extends nono's base `claude-code` profile and adds GPU access. It allows read/write access to:

- The autoresearch-nono repo directory
- `~/.cache/autoresearch/` — training data and tokenizer
- `~/.cache/torch`, `~/.cache/huggingface` — framework caches
- `~/.cache/uv`, `~/.local/share/uv` — package manager cache
- `~/.nv`, `~/.triton` — GPU compilation caches
- `/tmp`, `/dev/shm` — runtime scratch space

Read-only access is granted to the specific `/proc` paths CUDA and PyTorch require: `/proc/driver/nvidia`, `/proc/meminfo`, `/proc/cpuinfo`, `/proc/self`, `/proc/version`, and `/proc/sys/vm/overcommit_memory`. Broad `/proc` access — which would expose writable kernel parameters via `/proc/sys` — is not granted.

Credential paths (`~/.aws`, `~/.ssh`) are absent from the allow list and are therefore blocked. Network access is restricted to the LLM API and HuggingFace. Both constraints are inherited by the training subprocess.

---

## Two features worth highlighting

**Audit log.** There is a difference between what the agent committed to git and what it actually did. git only records what was saved. nono records everything — every file it opened, every network call it made, every access that was blocked. An agent that reads `~/.ssh` and does nothing with it leaves no git trace, but it appears in the nono audit.

```bash
# git's view — what was committed
git -C workload log --oneline

# nono's view — what was actually touched
nono audit show <session-id> --json

# filter for blocked access attempts (null means none were recorded)
nono audit show <session-id> --json | jq '.denials // "no denials recorded"'
```

For a research context this is independently useful: it lets me confirm which data shards were accessed during evaluation, verify that the training subprocess is only reaching expected network endpoints, and identify unexpected behaviour in the CUDA compilation layer.

**Instruction verification.** Each corpus has an instruction file that tells the agent what experiment to run — the research question, the goal metric, what it may and may not modify. If that file gets accidentally changed between runs, the agent will run a different experiment than intended, with no warning. nono signs the instruction file before the first run using DSSE signed payloads with local key management, and verifies the signature at launch. If anything has changed, it refuses to start:

```
[nono] Checking attestation...
[nono] ABORT: attestation failed — program_ibd.md may have been tampered with.
```

---

## Getting started

One command starts the agent under enforcement:

```bash
./launch.sh
```

`launch.sh` does two things before the agent starts. First, it verifies the attestation bundle for the signed corpus program file — if `program.md` has been modified since it was signed, the launch is aborted:

```
[nono] Checking attestation...
[nono] ABORT: attestation failed — program.md may have been tampered with.
```

If attestation passes, it runs:

```bash
exec nono run \
    --profile claude-code-autoresearch \
    --allow-gpu \
    --allow-cwd \
    --workdir "${AUTORESEARCH_DIR}" \
    -- claude --dangerously-skip-permissions
```

- `--profile claude-code-autoresearch` — loads the sandbox profile, which defines exactly which paths and network endpoints are accessible. Everything else is blocked at the kernel level.
- `--allow-gpu` — grants access to the NVIDIA device nodes and driver interfaces needed for CUDA. Absent from the base profile by default since most agent workloads don't need it.
- `--allow-cwd` — adds the current working directory to the allow list, so the agent can read and write the repo it was launched from.
- `--workdir` — sets the sandbox root to the workload directory. The agent starts with that as its working directory.
- `--dangerously-skip-permissions` — tells Claude Code to skip its own interactive permission prompts. This is intentional: autoresearch needs the agent to run unattended overnight. Claude Code's prompts and nono's kernel enforcement address different problems — for an overnight run, the kernel boundary is the appropriate control.

The agent does not know it is sandboxed. Nothing in the training setup needs to change. The profile is available via the nono registry (`nono pull Kexin-xu-01/claude-autoresearch`), along with ready-to-use workloads for IBD, TCGA, and general web text at [autoresearch-nono](https://github.com/Kexin-xu-01/autoresearch-nono).

---

## Example Results on IBD data

![Autoresearch results on IBD data](output.png)

The chart shows 34 experiments run overnight on IBD clinical case reports. The y-axis is validation bits per byte (BPB) — a measure of how well the model compresses the text, where lower is better. Starting from a baseline of 1.09 BPB, the agent explored architectural changes including depth scaling, attention head configuration, SwiGLU activations, and grouped-query attention (GQA). 18 of the 34 experiments were kept as improvements, with the rest reverted. By morning, BPB had dropped to 0.76 — a roughly 30% reduction — without any manual intervention.

---

*Repo: [github.com/Kexin-xu-01/autoresearch-nono](https://github.com/Kexin-xu-01/autoresearch-nono)*
