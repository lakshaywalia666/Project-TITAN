#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run inside a disposable Linux VM with sudo." >&2
  exit 2
fi

cleanup() {
  ip netns delete titan-client 2>/dev/null || true
  ip netns delete titan-server 2>/dev/null || true
  ip link delete titan-br0 2>/dev/null || true
}
trap cleanup EXIT

cleanup
ip link add titan-br0 type bridge
ip link set titan-br0 up
ip netns add titan-client
ip netns add titan-server
ip link add titan-c-host type veth peer name titan-c-ns
ip link add titan-s-host type veth peer name titan-s-ns
ip link set titan-c-ns netns titan-client
ip link set titan-s-ns netns titan-server
ip link set titan-c-host master titan-br0
ip link set titan-s-host master titan-br0
ip link set titan-c-host up
ip link set titan-s-host up
ip -n titan-client addr add 10.77.0.2/24 dev titan-c-ns
ip -n titan-server addr add 10.77.0.3/24 dev titan-s-ns
ip -n titan-client link set lo up
ip -n titan-server link set lo up
ip -n titan-client link set titan-c-ns up
ip -n titan-server link set titan-s-ns up
ip netns exec titan-client ping -c 2 -W 1 10.77.0.3

echo "Namespace bridge path verified; cleanup runs automatically."

