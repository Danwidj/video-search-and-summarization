# Mock backend

A zero-GPU mock backend that mimics the backend, so the incident profile can run without a VM. It is its own `uv` project. It is a backup, not the real backend: verify UI and backend work on the VM, not against it.

## What is inside

| Folder | What it is |
|---|---|
| [base_profile_mock](base_profile_mock/README.md) | Port 7777: the agent, VST and inference in one process. `./start.sh --mode mock` uses it |

## Read more

- [Architecture: Containers](../.docs/architecture.md#level-1-containers): what each mock serves
