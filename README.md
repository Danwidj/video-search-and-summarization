# Incident Search and Reporting

<!-- TODO(video): pitch video goes here -->

A video-driven incident search and reporting system: upload a clip, get a structured incident report, review it, and search the evidence in plain language.

## What this is

This is a final year project built by students at Singapore Management University. It adds incident search and reporting on top of NVIDIA's Video Search and Summarization (VSS) blueprint.

A reviewer uploads a surveillance or anomaly clip in a web console. A vision-language model writes a structured, timestamped incident report (type, severity, summary, the people, instruments and assets involved) with evidence images cut from the video. Reviewers edit the report into new versions, mark one version official, search past incidents and evidence in natural language, ask questions about a report in a chat panel, and follow the totals on a dashboard.

## Get started

Everything this project adds lives in the incident profile:

- **Deploy and run it:** [incident profile README](deploy/docker/developer-profiles/dev-profile-incident/README.md)
- **How it is built:** [architecture](deploy/docker/developer-profiles/dev-profile-incident/.docs/architecture.md)
- **Goals and scope:** [action plan](deploy/docker/developer-profiles/dev-profile-incident/.docs/action-plan.md)
- **What works today:** [status](deploy/docker/developer-profiles/dev-profile-incident/.docs/status.md)

The rest of the repository is the upstream blueprint, which the project builds on.

## Remaining work

The [status document](deploy/docker/developer-profiles/dev-profile-incident/.docs/status.md) is the source of truth. In short:

- Run the held-out evaluation across several models; only the development pilots are done.
- Turn on model-written chat answers once that evaluation validates them; chat answers are rule-based today.
- Check the recent tracking and evidence fixes in a full end-to-end analysis; they are unit-tested only.
- Apply the pending database migrations that three dashboard chart views and the Library duration badge wait for.
- Give background analysis jobs an owner, so one console does not pick up another console's job.
- Finish report export to PDF; a report prints only through the browser today.
- Remove the unused report timeline from the report contract, and merge the next contract version.
- Do one more browser check of every screen after the latest interface fixes.

## Team

<!-- TODO(team): names, course, supervisor -->

Team details to be added.

## Acknowledgements and licence

Built on the [NVIDIA AI Blueprint for Video Search and Summarization](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization). The licence is unchanged from upstream: see [LICENSE](LICENSE).
