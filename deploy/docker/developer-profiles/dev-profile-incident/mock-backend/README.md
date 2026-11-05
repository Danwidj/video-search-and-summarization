# Mock backends

Two independent zero-GPU mock backends that mimic the backend, so the incident profile can run without a VM. Each is its own `uv` project. They are a backup, not the real backend: verify UI and backend work on the VM, not against them.

## What is inside

| Folder | What it is |
|---|---|
| [base_profile_mock](base_profile_mock/README.md) | Port 7777: the agent, VST and inference in one process. `./start.sh --mode mock` uses it |
| [search_profile_mock](search_profile_mock/README.md) | Port 7778: the stock search profile's routes plus incident search, run on its own |

## Read more

- [Architecture: Containers](../.docs/architecture.md#level-1-containers): what each mock serves
