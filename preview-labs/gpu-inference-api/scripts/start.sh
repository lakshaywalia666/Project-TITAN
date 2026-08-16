#!/usr/bin/env bash
set -eu

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

if [ ! -f .env ]; then
  echo "ERROR: .env is missing. Copy .env.example to .env and replace API_KEY." >&2
  exit 1
fi

if grep -q '^API_KEY=replace-this-' .env; then
  echo "ERROR: replace the example API_KEY before starting the server." >&2
  exit 1
fi

echo "Pulling the model-server image. Paid GPU time is running while this command executes."
docker compose pull

echo "Starting the model server. The first start also downloads the model."
docker compose up -d

echo
echo "Follow startup logs with:"
echo "  docker compose logs -f model-server"
echo
echo "When the logs report that the server is ready, run:"
echo "  ./scripts/test-api.sh"

