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
The mock backends do not provide an offline CSV or Postgres mode for the
incident console. Use the database-backed console and its documented seed or
evaluation commands instead.
