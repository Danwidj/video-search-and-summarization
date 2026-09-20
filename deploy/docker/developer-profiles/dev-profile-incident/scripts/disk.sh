#!/usr/bin/env bash
#
# Disk/volume usage (replaces the old `mdx-disk` shell alias from
# deploy/dotfiles/aliases.sh — same behavior, standalone script).
#
# Plain `docker system df` — worth having given the model-weight cache is
# exactly what down.sh / rebuild.sh are designed to avoid silently deleting;
# use this to see how much space it's actually using before deciding to
# reclaim it (see skills/vss-deploy-profile/references/teardown.md's "Full
# teardown").
#
# Runs on the VM against the local docker daemon.

docker system df -v
