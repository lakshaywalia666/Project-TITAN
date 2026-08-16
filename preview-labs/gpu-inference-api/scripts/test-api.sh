#!/usr/bin/env bash
set -eu

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

if [ ! -f .env ]; then
  echo "ERROR: .env is missing." >&2
  exit 1
fi

set -a
. ./.env
set +a

api_base="${API_BASE:-http://127.0.0.1:8000}"

echo "Checking the model list..."
curl --fail --silent --show-error \
  --header "Authorization: Bearer $API_KEY" \
  "$api_base/v1/models"

echo
echo
echo "Sending one chat request..."
curl --fail --silent --show-error \
  --header "Authorization: Bearer $API_KEY" \
  --header "Content-Type: application/json" \
  --data @requests/chat-request.json \
  "$api_base/v1/chat/completions"

echo

