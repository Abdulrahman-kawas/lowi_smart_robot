#!/usr/bin/env bash
# Phase 2 (no AWS): a private CA + certificates for a local Mosquitto broker.
#   BROKER_HOST=brain-pc.local BROKER_IP=192.168.0.10 ./make_local_certs.sh
# Output in ./local-certs: ca.crt, server.{crt,key}, spider-01.{crt,key}, spider-brain.{crt,key}
set -euo pipefail
HOST="${BROKER_HOST:-brain-pc.local}"
IP="${BROKER_IP:-192.168.0.10}"
OUT="${OUT:-./local-certs}"
mkdir -p "$OUT"
chmod 700 "$OUT"
cd "$OUT"

[[ -f ca.key ]] || openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
  -keyout ca.key -out ca.crt -subj "/CN=spider-local-ca"

issue() {  # <name> <CN> [subjectAltName]
  local name=$1 cn=$2 san=${3:-}
  openssl req -newkey rsa:2048 -nodes -keyout "$name.key" -out "$name.csr" -subj "/CN=$cn"
  if [[ -n "$san" ]]; then
    openssl x509 -req -in "$name.csr" -CA ca.crt -CAkey ca.key -CAcreateserial -days 825 \
      -out "$name.crt" -extfile <(printf "subjectAltName=%s" "$san")
  else
    openssl x509 -req -in "$name.csr" -CA ca.crt -CAkey ca.key -CAcreateserial -days 825 \
      -out "$name.crt"
  fi
  rm -f "$name.csr"
  chmod 600 "$name.key"
}

issue server "$HOST" "DNS:$HOST,IP:$IP"
issue spider-01 spider-01
issue spider-brain spider-brain
issue spider-gateway spider-gateway
issue spider-voice spider-voice
echo "Certificates in $OUT. Keep ca.key offline."
