# Stage 2 draft prompts (not registered)

Drafts of V1–V7 for the owner's review ([Stage 2 plan](../../docs/experiments/stage2-plan.md)). Each one is `contracts/experiments/p1/p1-v4-base.txt` with one inserted block taken from `annotation-guidelines-v1.0`. `<id>.diff` shows the change, and `registry-proposal.json` holds the proposed registry entries (SHA-256, hypothesis).

- **Not runnable:** the registry and the agent know only registered prompts.
- **After approval**, each draft is added unchanged with `prompt_registry.add(<id>, parent="p1-v4-base", text=..., hypothesis=...)`, and its SHA-256 must equal the one here.
- **A reworded draft is a new draft, never an edit after registration** (the registry is append-only).
- **V8** is not drafted. It is built after Stage 2a by the rule in the plan.
