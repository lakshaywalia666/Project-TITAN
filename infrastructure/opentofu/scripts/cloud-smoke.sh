#!/usr/bin/env bash
set -Eeuo pipefail

if [ "${TITAN_CONFIRM:-}" != "DEPLOY_AND_DESTROY_TITAN" ]; then
  echo "Refusing cloud mutation: set TITAN_CONFIRM=DEPLOY_AND_DESTROY_TITAN" >&2
  exit 64
fi

for command in tofu curl date ssh ssh-keygen; do
  command -v "$command" >/dev/null || {
    echo "required command is missing: $command" >&2
    exit 69
  }
done

PROVIDER="${TITAN_PROVIDER:-}"
IMAGE="${TITAN_IMAGE:-}"
OWNER="${TITAN_OWNER:-}"
case "$PROVIDER" in
  aws|azure|gcp) ;;
  *) echo "TITAN_PROVIDER must be aws, azure or gcp" >&2; exit 64 ;;
esac
if [[ ! "$IMAGE" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "TITAN_IMAGE must be a public digest-pinned GHCR image" >&2
  exit 64
fi
if [[ ! "$OWNER" =~ ^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$ ]]; then
  echo "TITAN_OWNER must be a lowercase label of 1-63 letters, digits, hyphens or underscores" >&2
  exit 64
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OPENTOFU_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORK="$(mktemp -d -t titan-cloud-smoke.XXXXXXXX)"
APPLY_ATTEMPTED=0
PUBLIC_IP=""
SSH_USER=""
export TF_IN_AUTOMATION=1
export TF_INPUT=0

cp -R "$OPENTOFU_ROOT/$PROVIDER" "$WORK/module"
cp -R "$OPENTOFU_ROOT/shared" "$WORK/shared"
ssh-keygen -q -t ed25519 -N '' -f "$WORK/operator-key"
RUNNER_IP="$(curl --fail --silent --show-error https://checkip.amazonaws.com | tr -d '\r\n')"
if [[ ! "$RUNNER_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "could not determine a valid runner IPv4 address" >&2
  exit 69
fi
EXPIRES_AT="$(date -u -d '+4 hours' '+%Y-%m-%dT%H:%M:%SZ')"

VARS=(
  -var "owner=$OWNER"
  -var "operator_cidr=$RUNNER_IP/32"
  -var "ssh_public_key=$(cat "$WORK/operator-key.pub")"
  -var "titan_image=$IMAGE"
  -var "expires_at=$EXPIRES_AT"
)

case "$PROVIDER" in
  aws)
    VARS+=(-var "aws_region=${AWS_REGION:-ap-south-1}")
    SSH_USER=ubuntu
    ;;
  azure)
    : "${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID is required}"
    VARS+=(
      -var "subscription_id=$AZURE_SUBSCRIPTION_ID"
      -var "location=${AZURE_LOCATION:-centralindia}"
    )
    SSH_USER=titan
    ;;
  gcp)
    : "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
    VARS+=(
      -var "project_id=$GCP_PROJECT_ID"
      -var "region=${GCP_REGION:-us-central1}"
      -var "zone=${GCP_ZONE:-us-central1-a}"
    )
    SSH_USER=titan
    ;;
esac

cleanup() {
  local original_status=$?
  trap - EXIT INT TERM
  if [ "$APPLY_ATTEMPTED" -eq 1 ]; then
    echo "Destroying the $PROVIDER smoke environment..."
    destroyed=0
    for destroy_attempt in 1 2 3; do
      if tofu -chdir="$WORK/module" destroy -auto-approve "${VARS[@]}"; then
        destroyed=1
        break
      fi
      echo "Destroy attempt $destroy_attempt failed; retrying..." >&2
      sleep "$((destroy_attempt * 10))"
    done
    if [ "$destroyed" -ne 1 ]; then
      echo "CRITICAL: automatic destroy failed; inspect the $PROVIDER console immediately." >&2
      original_status=1
    fi
  fi
  rm -rf -- "$WORK"
  exit "$original_status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

tofu -chdir="$WORK/module" init -backend=false -input=false
tofu -chdir="$WORK/module" validate
tofu -chdir="$WORK/module" plan -input=false -out="$WORK/titan.plan" "${VARS[@]}"
APPLY_ATTEMPTED=1
tofu -chdir="$WORK/module" apply -auto-approve "$WORK/titan.plan"
PUBLIC_IP="$(tofu -chdir="$WORK/module" output -raw public_ip)"

SSH_OPTIONS=(
  -i "$WORK/operator-key"
  -o BatchMode=yes
  -o ConnectTimeout=5
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$WORK/known_hosts"
)

echo "Waiting for SSH and TITAN bootstrap on $PROVIDER..."
for attempt in $(seq 1 60); do
  if ssh "${SSH_OPTIONS[@]}" "$SSH_USER@$PUBLIC_IP" 'sudo titan-health' 2>/dev/null; then
    echo "TITAN_CLOUD_SMOKE_OK provider=$PROVIDER ip=$PUBLIC_IP"
    exit 0
  fi
  if [ "$attempt" -eq 60 ]; then
    ssh "${SSH_OPTIONS[@]}" "$SSH_USER@$PUBLIC_IP" \
      'sudo systemctl status titan-smoke --no-pager; sudo journalctl -u titan-smoke -n 200 --no-pager' || true
    echo "TITAN smoke verification timed out" >&2
    exit 1
  fi
  sleep 10
done
