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
#   vm_host_ip                       print this VM's address (the source address of the route to 1.1.1.1); nothing when it has none
#   vm_env_defaults <file> <profile-dir>
#                                    export VSS_APPS_DIR (the checkout's deploy/docker), VSS_DATA_DIR
#                                    (<checkout>/.data) and HOST_IP (vm_host_ip) when the shell and the file
#                                    all leave them blank. A filled-in value wins, and nothing is created here.
#                                    Returns 1 with a message when HOST_IP is blank and the VM has no address.
#   vm_env_load <file> <profile-dir> vm_env_defaults, then export every setting in the file. The defaulted
#                                    settings are exported first and their blank lines skipped, so settings
#                                    built from them (VST_INTERNAL_URL, PHOENIX_ENDPOINT) get the real value.

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

vm_host_ip() {
  ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n 1
}

vm_env_defaults() {
  local env_file="$1" profile_dir="$2" docker_dir host_ip
  docker_dir="$(cd "${profile_dir}/../.." && pwd)"
  if [ -z "${VSS_APPS_DIR:-}" ] && [ -z "$(vm_env_value "$env_file" VSS_APPS_DIR)" ]; then
    export VSS_APPS_DIR="$docker_dir"
  fi
  if [ -z "${VSS_DATA_DIR:-}" ] && [ -z "$(vm_env_value "$env_file" VSS_DATA_DIR)" ]; then
    export VSS_DATA_DIR="$(cd "${docker_dir}/../.." && pwd)/.data"
  fi
  if [ -z "${HOST_IP:-}" ] && [ -z "$(vm_env_value "$env_file" HOST_IP)" ]; then
    host_ip="$(vm_host_ip)"
    if [ -z "$host_ip" ]; then
      echo "env-file: cannot determine this VM's address ('ip -4 route get 1.1.1.1' gave none) and HOST_IP is blank in ${env_file}. Set HOST_IP there to the VM's LAN address." >&2
      return 1
    fi
    export HOST_IP="$host_ip"
  fi
  return 0
}

vm_env_load() {
  local env_file="$1" profile_dir="$2"
  vm_env_defaults "$env_file" "$profile_dir" || return 1
  set -a
  # eval, not source <(...): bash 3.2 (the laptop's) cannot source a process substitution.
  eval "$(sed -E "/^(HOST_IP|VSS_APPS_DIR|VSS_DATA_DIR)=([[:space:]]*|\"\"|'')\$/d" "$env_file")"
  set +a
  return 0
}
