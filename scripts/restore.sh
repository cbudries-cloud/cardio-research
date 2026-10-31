#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into the stack, REPLACING its current data.
#
#   scripts/restore.sh <backup-dir> --yes-replace-current-data
#
# Destructive: the current database and document store are dropped first. Make a fresh
# backup before restoring over data you care about.
set -euo pipefail
cd "$(dirname "$0")/.."

src=${1:?usage: restore.sh <backup-dir> --yes-replace-current-data}
[[ "${2:-}" == "--yes-replace-current-data" ]] || { echo "Refusing without --yes-replace-current-data" >&2; exit 1; }

source scripts/lib/disposable.sh
project=$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
if [[ "${CARDIO_RESTORE_TEST:-}" == "1" ]]; then
  check_disposable_name "$project"   # automated tests may only restore into disposable projects
fi
echo "Restoring into Compose project '$project' (its current data will be replaced)" >&2

(cd "$src" && shasum -a 256 -c SHA256SUMS >/dev/null) || { echo "Checksum verification failed" >&2; exit 1; }

suffix=""
[[ -f "$src/database.dump.enc" ]] && suffix=".enc"
decrypt() {  # file -> stdout
  if [[ -n "$suffix" ]]; then
    : "${CARDIO_BACKUP_PASSPHRASE_FILE:?encrypted backup: set CARDIO_BACKUP_PASSPHRASE_FILE}"
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$CARDIO_BACKUP_PASSPHRASE_FILE" -in "$1"
  else
    cat "$1"
  fi
}

docker compose up -d --wait db
docker compose stop api web >/dev/null 2>&1 || true

docker compose exec -T db dropdb -U cardio --force --if-exists cardio
docker compose exec -T db createdb -U cardio cardio
decrypt "$src/database.dump$suffix" | docker compose exec -T db pg_restore -U cardio -d cardio --no-owner --exit-on-error

decrypt "$src/documents.tar$suffix" | docker compose run --rm --no-deps -T --entrypoint sh api \
  -c 'find /data/documents -mindepth 1 -delete && tar -C /data/documents -xf -'

docker compose up -d --wait api web
echo "Restored from $src"
