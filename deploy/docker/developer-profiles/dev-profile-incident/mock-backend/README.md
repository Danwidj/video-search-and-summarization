# mock-backend

Parent directory for independent mock backends used in local development. Each
sibling is its own package with its own `pyproject.toml` - `uv sync`/run one without
touching another.

- [`base_profile_mock/`](base_profile_mock/README.md) - mocks the entire
  `bp_developer_base` backend (vss-agent API + VIOS/VST + LLM/VLM inference) so the
  real UI can be developed against it with zero GPU and zero NIM containers.
- `mock_data/` (if present) - mocks a separate, not-yet-built Postgres schema for the
  planned "incident-console" Streamlit app described in `docs/incident-plan/`. Unrelated
  to `base_profile_mock/` - do not conflate the two.
