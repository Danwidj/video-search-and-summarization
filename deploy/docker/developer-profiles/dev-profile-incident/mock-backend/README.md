# Mock backends

Two independent zero-GPU mock backends for testing the incident profile without a VM. Each is its own `uv` project. Use them only for the mock backend's own unit tests, never for UI or backend work.

## What is inside

| Folder | What it is |
|---|---|
| [base_profile_mock](base_profile_mock/README.md) | Port 7777: the agent, VST and inference in one process. `./start.sh --mode mock` uses it |
| [search_profile_mock](search_profile_mock/README.md) | Port 7778: the stock search profile's routes plus incident search, run on its own |

## Read more

- [Architecture: Containers](../.docs/architecture.md#level-1-containers): what each mock serves
