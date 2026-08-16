#!/usr/bin/env bash
set -eu

required_commands="docker nvidia-smi curl"

for command_name in $required_commands; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $command_name" >&2
    exit 1
  fi
done

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose v2 is not available." >&2
  exit 1
fi

echo "GPU detected:"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

echo
echo "Docker detected:"
docker version --format 'Client: {{.Client.Version}} | Server: {{.Server.Version}}'

echo
echo "Docker Compose detected:"
docker compose version

echo
echo "Available space in the current filesystem:"
df -h .

echo
echo "Host checks passed. This does not start or download anything."

