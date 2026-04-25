# Running an AI agent overnight on medical text

Last month I set up Andrej Karpathy's autoresearch to run overnight on medical pathology text. The idea: give an AI agent a training script, a fixed time budget, and a metric to optimise, then let it experiment while you sleep. By morning, you have dozens of experiments charted — architectural changes, learning rate schedules, batch size sweeps — that would take weeks to work through manually.

I am a third-year PhD student in Computational Biology, working on applying AI to inflammatory bowel disease. Alongside that, I am interested in multi-agent AI for scientific research — which led me to join Always Further as an AI Researcher in February 2026. Autoresearch is a concrete example of that: an AI agent running autonomously on a scientific workload. To demonstrate the setup, I used two publicly available medical corpora: IBD clinical case reports from the [MultiCaRe dataset](https://zenodo.org/records/10079370), and TCGA cancer pathology reports.

But before I let it run unattended overnight, I needed to think about what I was actually leaving running on my machine.

---

## The problem

Autoresearch works by giving an AI agent unrestricted write access to a training codebase. The agent calls the LLM API, modifies `train.py`, spawns a GPU training subprocess, reads the results, and commits or resets — in a loop, all night.

That GPU subprocess runs arbitrary Python with full network access, on a machine that holds AWS credentials and SSH keys.

The agent's safety boundary today is entirely behavioural: it stays on task because it has been instructed to. Application-level filtering helps for the agent itself, but does nothing for the subprocesses it spawns. If the agent drifts — through a model quirk, an unexpected prompt, or content in the training data — there is no structural barrier.

---

## Why nono

[nono](https://github.com/lukehinds/nono) is a kernel-level sandbox for AI agents, built on Linux Landlock and macOS Seatbelt. The critical property: restrictions applied to a process automatically cascade to every subprocess it spawns. The training subprocess inherits the same constraints as the agent — no extra configuration, no gaps.

I started with `nono learn` to generate a base policy from the real process footprint, then extended it manually, particularly for GPU access — CUDA, Triton, and the NVIDIA driver touch paths that are not obvious until something breaks.

The resulting profile restricts the agent and its subprocesses to exactly what autoresearch legitimately needs:

| Without nono | With nono |
|---|---|
| Agent can read `~/.aws`, `~/.ssh` | Blocked at kernel level |
| Agent can write to any file | Write access limited to repo + cache dirs |
| Training subprocess has full network access | Network restricted to LLM API + HuggingFace |
| No record of what was actually accessed | Structured audit log of every operation |
| Instruction file can be silently modified | Tamper detection via Sigstore attestation |

---

## Two features worth highlighting

**Audit log.** git records what the agent committed. nono records what it actually touched — every file access, every network call, every denial. For a research context, this is independently useful: I can confirm exactly which data shards were read during evaluation and verify that no unexpected network traffic occurred.

**Attestation.** Each corpus has an instruction file (`ibd/program_ibd.md`, `tcga/program_tcga.md`) that tells the agent what to research. If this file is modified between runs — stale git state, merge error, anything — the agent executes under a different mandate with no visible indication. nono's attestation layer signs the instruction file and verifies it at launch. If verification fails, the run aborts before the agent starts.

---

## Getting started

The launch wrapper handles attestation verification and starts Claude Code under kernel enforcement with a single command. The profile will be available via the nono profile registry; for now it is in the `profiles/` directory of [autoresearch-nono](https://github.com/Kexin-xu-01/autoresearch-nono), along with workloads for IBD, TCGA cancer reports, and general web text.

The agent is unaware of the sandbox. Nothing in the training pipeline requires modification. nono sits below the application layer and enforces the boundary there.

---

*Repo: [github.com/Kexin-xu-01/autoresearch-nono](https://github.com/Kexin-xu-01/autoresearch-nono)*
