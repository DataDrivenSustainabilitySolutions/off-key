#!/usr/bin/env bash
set -euo pipefail
umask 077
# The broker certificate names DNS:emqx-main, the network alias every MQTT client
# dials; the Mosquitto service answers on it (docs/operations/mqtt-broker.md).

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 OUTPUT_DIRECTORY_OUTSIDE_THE_REPOSITORY" >&2
  exit 2
fi

output=$1
if [ -e "$output" ]; then
  echo "Refusing to overwrite existing directory: $output" >&2
  exit 1
fi
mkdir -m 700 -- "$output"
trap 'rm -f "$output/broker.csr" "$output/broker.ext" "$output/ca.srl"' EXIT

read -r -s -p "New CA key passphrase (at least 12 characters): " ca_password
echo
if [ "${#ca_password}" -lt 12 ]; then
  echo "CA passphrase must be at least 12 characters" >&2
  exit 1
fi

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -aes-256-cbc -pass fd:3 -out "$output/ca.key" 3<<<"$ca_password"
openssl req -new -x509 -sha256 -days 3650 \
  -key "$output/ca.key" -passin fd:3 -out "$output/ca.crt" \
  -subj "/CN=Off Key Internal MQTT CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" 3<<<"$ca_password"

openssl req -new -newkey rsa:3072 -nodes \
  -keyout "$output/broker.key" -out "$output/broker.csr" \
  -subj "/CN=emqx-main"
cat > "$output/broker.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:emqx-main
EOF
openssl x509 -req -sha256 -days 365 \
  -in "$output/broker.csr" -CA "$output/ca.crt" -CAkey "$output/ca.key" \
  -passin fd:3 -CAcreateserial -out "$output/broker.crt" \
  -extfile "$output/broker.ext" 3<<<"$ca_password"
unset ca_password
openssl verify -CAfile "$output/ca.crt" -verify_hostname emqx-main \
  "$output/broker.crt"
echo "Generated CA and broker certificate in $output"
echo "Keep ca.key encrypted and offline. Put only ca.crt, broker.crt and broker.key in Ansible Vault (emqx_ca_cert, emqx_server_cert, emqx_server_key)."
