# Incident Search and Reporting

<a href="https://youtu.be/_THMlaojpK8">
  <img src="https://img.youtube.com/vi/_THMlaojpK8/maxresdefault.jpg" alt="Watch the pitch video" width="100%">
</a>

> **Pitch video:** [watch on YouTube](https://youtu.be/_THMlaojpK8)

A video-driven incident search and reporting system: upload a clip, get a structured incident report, review it, and search the evidence in plain language.

## What this is

This is a final year project built by students at Singapore Management University. It adds incident search and reporting on top of NVIDIA's Video Search and Summarization (VSS) blueprint.

A reviewer uploads a surveillance or anomaly clip in a web console. A vision-language model writes a structured, timestamped incident report (type, severity, summary, the people, instruments and assets involved) with evidence images cut from the video. Reviewers edit the report into new versions, mark one version official, search past incidents and evidence in natural language, ask questions about a report in a chat panel, and follow the totals on a dashboard.

## Architecture

![Containers of the incident system](deploy/docker/developer-profiles/dev-profile-incident/.docs/figures/figure-2-containers.drawio.svg)

## Hardware requirements

The incident profile deploys perception containers and a native agent locally on a GPU host, whilst language and vision model inference is hosted remotely:

- **Tested configuration:** developed and tested on an Ubuntu workstation with an NVIDIA RTX A6000 (48 GB VRAM, pinned to GPU 0; ~7.6 GB VRAM held by perception while active, ~40 GB disk for images).
- **Upstream VSS minimums:** an x86 host with an 18-core CPU, 128 GB RAM, 1 TB SSD storage, 1 Gbps network, Ubuntu 24.04, NVIDIA driver (>= 595.58.03), Docker Engine (>= 28.3.3, < 29.5.0) with Compose (>= v2.39.1), and NVIDIA Container Toolkit (>= 1.17.8).
- **Client laptop:** runs the web console; requires Node.js, npm, uv, and SSH connectivity to the GPU host.

Detailed deployment prerequisites, container footprints, and operations are documented in the [incident profile operations guide](deploy/docker/developer-profiles/dev-profile-incident/.docs/incident-profile-operations.md).

## Get started

Deploy and run it from the [incident profile README](deploy/docker/developer-profiles/dev-profile-incident/README.md). The rest of the repository is the upstream blueprint, which the project builds on.

## Acknowledgements and licence

Built on the [NVIDIA AI Blueprint for Video Search and Summarization](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization). The licence is unchanged from upstream: see [LICENSE](LICENSE).
