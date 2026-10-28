# Stage 2 draft prompts (history; registered 2026-10-28)

> **Registered** with `prompt_registry.add`: see the [prompt record](../../docs/experiments/stage2-prompts.md). V1–V4, V6 and V7 are byte-identical to these drafts. V5 (`p1-v4-e05-descriptions`) was registered with one more bullet, on completeness and consistency with the structured fields (SHA-256 `416b6790b230…`, not the draft's `fac6f74aaa1d…`), following the owner's V5 description of 2026-10-28. These drafts are kept unchanged as history.

Drafts of V1–V7 for the owner's review ([Stage 2 plan](../../docs/experiments/stage2-plan.md)). Each one is `contracts/experiments/p1/p1-v4-base.txt` with one inserted block taken from `annotation-guidelines-v1.0`. `<id>.diff` shows the change, and `registry-proposal.json` holds the proposed registry entries (SHA-256, hypothesis).

- **Not runnable:** the registry and the agent know only registered prompts.
- **After approval**, each draft is added unchanged with `prompt_registry.add(<id>, parent="p1-v4-base", text=..., hypothesis=...)`, and its SHA-256 must equal the one here.
- **A reworded draft is a new draft, never an edit after registration** (the registry is append-only).
- **V8** is not drafted. It is built after Stage 2a by the rule in the plan.
