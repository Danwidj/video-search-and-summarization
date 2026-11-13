# Experiment prompt registry

An append-only registry of P1 prompts for the prompt experiments. It is not the production contract: `sync.py` does not vendor these files, and the console and the agent's default path never read them. The agent reads one only behind `INCIDENT_EXPERIMENTS_ENABLED=1`.

## What is inside

| File | What it is |
|---|---|
| [registry.json](registry.json) | One entry per prompt: `id`, `parent`, `file`, `sha256`, `contract_version`, `guidelines`, `hypothesis`, `created`, `status` (`baseline` or `candidate`) |
| [p1/](p1) | The exact prompt text, one `<id>.txt` per entry. Never edited after it is registered |

## Add a prompt

Run this from `eval/`:

```bash
uv run python -c "import prompt_registry as r; r.add('p1-v4-e01-severity', parent='p1-v4-base', text=open('draft.txt').read(), hypothesis='...')"
```

## Rules

`eval/prompt_registry.py` and `eval/tests/test_prompt_registry.py` enforce these:
- **Immutable:** every file matches its recorded SHA-256. `prompt_text` refuses to serve a changed file.
- **Append-only:** compared with `origin/main`, entries are only added, never edited, reordered or removed. A changed prompt gets a new id with the old one as `parent`.
- **Baseline:** `p1-v4-base` is byte-identical to `../incident_extraction_prompt.txt` at `incident-contract-v4`.
- **Ids:** `p1-v<contract>-e<NN>-<topic>`. Each experiment prompt has a written hypothesis and an existing earlier parent.
- **Selection** is recorded in the PR description, never as an edit to an entry.

## Read more

- [Incident contract](../README.md): the production prompt and schema
