#!/usr/bin/env bash
set -eu

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

docker compose down

echo
echo "The container is stopped, but the rented machine may still be billing."
echo "Terminate or stop the GPU instance in the provider console, then verify its status there."

