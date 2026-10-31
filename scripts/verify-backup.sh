#!/usr/bin/env bash
# Verify a backup of the working stack by restoring it into a disposable, isolated project and
# comparing digests. The working project is only read (GET requests); nothing is written to it.
#
#   CARDIO_BACKUP_PASSPHRASE_FILE=~/.cardio-pass scripts/verify-backup.sh <backup-dir>
#
# Prints digests and counts only, never record contents.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/disposable.sh

src=${1:?usage: verify-backup.sh <backup-dir>}
WORKING_API="http://127.0.0.1:${API_PORT:-8000}/api/v1"
working=$(python3 scripts/lib/fingerprint.py "$WORKING_API" --digest)

export COMPOSE_PROJECT_NAME=cardio-restore-test
use_empty_secrets_dir
export WEB_PORT=${RESTORE_TEST_WEB_PORT:-13100}
export API_PORT=${RESTORE_TEST_API_PORT:-18100}
export CARDIO_RESTORE_TEST=1
trap disposable_down EXIT

disposable_down
docker compose up -d --build --wait db api >/dev/null
scripts/restore.sh "$src" --yes-replace-current-data >/dev/null 2>&1
restored=$(python3 scripts/lib/fingerprint.py "http://127.0.0.1:$API_PORT/api/v1" --digest)

echo "working:  $working"
echo "restored: $restored"
[[ "$working" == "$restored" ]] || { echo "FAIL: restored state differs from the working stack" >&2; exit 1; }
if docker compose exec -T db psql -U cardio -d cardio -v ON_ERROR_STOP=1 -c \
    "update observations set original_value='tampered'" >/dev/null 2>&1; then
  echo "FAIL: immutability trigger missing after restore" >&2; exit 1
fi
echo "PASS: backup restores to an identical state; integrity triggers intact"
