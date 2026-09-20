#!/usr/bin/env bash
#
# One-shot GPU status, on demand (replaces the old `gpu` shell alias from
# deploy/dotfiles/aliases.sh — same behavior, standalone script).
#
# Deliberately not a starship module: Starship has no built-in nvidia
# module, and the only way to add one is a [custom.gpu] shell-out on *every*
# prompt render (tens-to-100+ ms latency for info that's usually stale by
# the time it's read). This gives the same info with zero per-prompt cost.
# Runs on the VM (or anywhere nvidia-smi exists).

nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
