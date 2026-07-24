#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_HOST:?set PUBLIC_HOST to the deployed hostname}"

invalid_host() {
  echo "invalid PUBLIC_HOST" >&2
  exit 2
}

if (( ${#PUBLIC_HOST} > 253 )) \
  || [[ ! "$PUBLIC_HOST" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] \
  || [[ "$PUBLIC_HOST" == *..* ]]; then
  invalid_host
fi

IFS='.' read -r -a host_labels <<< "$PUBLIC_HOST"
for host_label in "${host_labels[@]}"; do
  if (( ${#host_label} > 63 )) \
    || [[ "$host_label" == -* ]] \
    || [[ "$host_label" == *- ]]; then
    invalid_host
  fi
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
output_path="${OUTPUT_PATH:-/tmp/devils-committee.nginx.conf}"
output_dir="$(dirname -- "$output_path")"
output_name="$(basename -- "$output_path")"
mkdir -p -- "$output_dir"
temporary_path="$(mktemp "$output_dir/.${output_name}.tmp.XXXXXX")"
trap 'rm -f -- "$temporary_path"' EXIT
export PUBLIC_HOST

envsubst '${PUBLIC_HOST}' \
  < "$repo_root/deploy/nginx/devils-committee.conf.template" \
  > "$temporary_path"
chmod 0644 "$temporary_path"
mv -f -- "$temporary_path" "$output_path"
trap - EXIT
