# mock-backend

Parent directory for independent mock backends used in local development. Each
sibling is its own package with its own `pyproject.toml` - `uv sync`/run one without
touching another.

- [`base_profile_mock/`](base_profile_mock/README.md) - mocks the entire
  `bp_developer_base` backend (vss-agent API + VIOS/VST + LLM/VLM inference) so the
  real UI can be developed against it with zero GPU and zero NIM containers.
- [`search_profile_mock/`](search_profile_mock/README.md) - strict superset of
  `base_profile_mock` for `bp_developer_search`: all base routes plus agent
  search endpoints, VST sensor list, video-analytics-api `/frames`, Kibana
  stubs, and Elasticsearch/Logstash info stubs (port 7778, zero GPU).
- `mock_data/` (if present) - mocks a separate, not-yet-built Postgres schema for the
  planned "incident-console" Streamlit app described in `docs/incident-plan/`. Unrelated
  to `base_profile_mock/` - do not conflate the two.

## ⚠️ CRITICAL WARNING for `base_profile_mock` users

**Never set `INCIDENT_DB_DSN` to the shared/team Supabase Postgres project when
running the console against `base_profile_mock`.** The mock fabricates fake video
and report data (with `sensor-<hash>` IDs and `mock://` report paths) and writes
it straight into the real shared catalog. These phantom rows are indistinguishable
from real data until someone traces the `sensor-<hash>` ID shape. This has
already happened multiple times, polluting the shared catalog with 12+ fake
incidents that had no real video bytes behind them.

**Safe alternatives:** leave `INCIDENT_DB_DSN` empty/unset (offline mode) or use
a personal/throwaway database. See
[`base_profile_mock/README.md`](base_profile_mock/README.md) for full details.
