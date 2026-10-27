# Experiment prompt registry

Append-only registry of P1 prompts for the prompt experiments (plan §F.3). **Not the production contract:** `sync.py` does not vendor these files, and the console and the agent's default path never read them. The agent reads one only behind `INCIDENT_EXPERIMENTS_ENABLED=1` (PR 6B).

| File | What |
|---|---|
| `registry.json` | One entry per prompt: `id`, `parent`, `file`, `sha256`, `contract_version`, `guidelines`, `hypothesis`, `created`, `status` (`baseline` or `candidate`) |
| `p1/<id>.txt` | The exact prompt text. Never edited after it is registered |

## Rules

Enforced by `eval/prompt_registry.py` and `eval/tests/test_prompt_registry.py`:
- **Immutable:** every file must match its recorded SHA-256. `prompt_text` refuses to serve a changed file.
- **Append-only:** compared with `origin/main`, entries may only be added, never edited, reordered or removed. A changed prompt gets a new id with the old one as `parent`.
- **Baseline:** `p1-v4-base` is byte-identical to `../incident_extraction_prompt.txt` at `incident-contract-v4`.
- **Ids:** `p1-v<contract>-e<NN>-<topic>`. Each experiment prompt has a written hypothesis and an existing earlier parent.
- **Selection** is recorded in `.docs/decisions.md`, never as an edit to an entry.

Add a prompt from `eval/`:

```bash
uv run python -c "import prompt_registry as r; r.add('p1-v4-e01-severity', parent='p1-v4-base', text=open('draft.txt').read(), hypothesis='...')"
```
