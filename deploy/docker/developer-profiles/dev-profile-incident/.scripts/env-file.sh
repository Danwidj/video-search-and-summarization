#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# env-file.sh - VM SIDE. Sourced by native-services.sh, tracking-stack.sh and rebuild-svc.sh.
# (vm-ensure-docker.sh is piped over SSH and cannot source this file, so it carries the same
# logic inline; test-vm-ensure-docker.sh and test-env-file.sh keep the two in step.)
#
#   vm_env_file <profile-dir>        print the VM env file: .env.remote, else the old name generated.env.remote
#                                    (a note on stderr when both exist: .env.remote wins); nothing when neither exists
#   vm_env_value <file> <key>        read one key without sourcing the file (it holds secrets); blank when absent
#   vm_env_defaults <file> <profile-dir>
#                                    export VSS_APPS_DIR (the checkout's deploy/docker) and VSS_DATA_DIR
#                                    (<checkout>/.data) when the shell and the file both leave them blank.
#                                    A filled-in value wins, and nothing is created here.

vm_env_file() {
  local profile_dir="$1"
  if [ -f "${profile_dir}/.env.remote" ]; then
    [ -f "${profile_dir}/generated.env.remote" ] &&
      echo "env-file: both .env.remote and generated.env.remote exist in ${profile_dir}; using .env.remote." >&2
    echo "${profile_dir}/.env.remote"
  elif [ -f "${profile_dir}/generated.env.remote" ]; then
    echo "${profile_dir}/generated.env.remote"
  fi
  return 0
}

vm_env_value() {
  sed -n "s/^$2=//p" "$1" | head -n 1 | sed -e "s/[[:space:]]*#.*$//" -e "s/^[\"']//" -e "s/[\"']$//"
}

vm_env_defaults() {
  local env_file="$1" profile_dir="$2" docker_dir
  docker_dir="$(cd "${profile_dir}/../.." && pwd)"
  if [ -z "${VSS_APPS_DIR:-}" ] && [ -z "$(vm_env_value "$env_file" VSS_APPS_DIR)" ]; then
    export VSS_APPS_DIR="$docker_dir"
  fi
  if [ -z "${VSS_DATA_DIR:-}" ] && [ -z "$(vm_env_value "$env_file" VSS_DATA_DIR)" ]; then
    export VSS_DATA_DIR="$(cd "${docker_dir}/../.." && pwd)/.data"
  fi
  return 0
}
