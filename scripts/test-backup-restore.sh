#!/usr/bin/env bash
# Backup-and-restore test on an isolated stack:
#   load synthetic records -> fingerprint -> backup -> destroy all volumes ->
#   fresh empty stack -> restore -> fingerprint must match exactly; integrity triggers intact.
# Runs once plaintext and once encrypted. Never touches the development stack.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/disposable.sh

export COMPOSE_PROJECT_NAME=cardio-restore-test
use_empty_secrets_dir
export WEB_PORT=${RESTORE_TEST_WEB_PORT:-13100}
export API_PORT=${RESTORE_TEST_API_PORT:-18100}
API="http://127.0.0.1:$API_PORT/api/v1"
WORK=$(mktemp -d)
export CARDIO_BACKUP_DIR="$WORK/backups"
export CARDIO_RESTORE_TEST=1   # restore.sh refuses non-disposable projects in this mode

cleanup() { disposable_down; rm -rf "$WORK"; }
trap cleanup EXIT

post() { curl -sf -H "X-Cardio-Client: web" "$@"; }
jget() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

load_data() {
  for f in synthetic_venous_panel_2022.csv synthetic_lab_report_2024.pdf synthetic_edge_cases.csv \
           synthetic_lab_report_2024_corrected.pdf synthetic_scanned_image_only.pdf; do
    post -F "file=@fixtures/synthetic/$f" "$API/documents" >/dev/null
  done
  # Accept everything acceptable, correct one blocked candidate, resolve one flag.
  ids=$(curl -sf "$API/observations?verification_status=unverified" | python3 -c "
import json,sys
for o in json.load(sys.stdin):
    print(o['id'], 'blocked' if o['blocking_issues'] else 'ok')")
  while read -r id state; do
    [[ $state == ok ]] && post -X POST -H 'Content-Type: application/json' \
      -d '{"confirm_source_matches":true}' "$API/observations/$id/accept" >/dev/null || true
  done <<< "$ids"
  blocked=$(echo "$ids" | awk '$2=="blocked"{print $1; exit}')
  post -X POST -H 'Content-Type: application/json' -d '{"unit":"mg/dL","collection_date":"2024-06-03","value":"1","reason":"restore test"}' \
    "$API/observations/$blocked/correct" >/dev/null
  flag=$(curl -sf "$API/flags" | jget "[0]['id']")
  post -X POST -H 'Content-Type: application/json' -d '{"resolution":"acknowledged"}' "$API/flags/$flag/resolve" >/dev/null || \
  post -X POST -H 'Content-Type: application/json' -d '{"resolution":"distinct_measurements"}' "$API/flags/$flag/resolve" >/dev/null
}

fingerprint() { python3 scripts/lib/fingerprint.py "$API"; }

check_triggers() {
  if docker compose exec -T db psql -U cardio -d cardio -v ON_ERROR_STOP=1 -c \
      "update observations set original_value='tampered'" >/dev/null 2>&1; then
    echo "FAIL: immutability trigger missing after restore" >&2; exit 1
  fi
  if docker compose exec -T db psql -U cardio -d cardio -v ON_ERROR_STOP=1 -c \
      "delete from audit_events" >/dev/null 2>&1; then
    echo "FAIL: audit append-only trigger missing after restore" >&2; exit 1
  fi
}

run_case() {
  local label=$1
  disposable_down
  docker compose up -d --build --wait db api >/dev/null
  load_data
  fingerprint > "$WORK/before.json"
  local n; n=$(python3 -c "import json;d=json.load(open('$WORK/before.json'));print(len(d['observations']), len(d['documents']))")
  backup_dir=$(scripts/backup.sh)
  if [[ -n "${CARDIO_BACKUP_PASSPHRASE_FILE:-}" ]]; then
    [[ "$(head -c 8 "$backup_dir/database.dump.enc")" == "Salted__" ]] || { echo "FAIL: dump not encrypted" >&2; exit 1; }
    ! grep -q "SYNTHETIC" "$backup_dir/documents.tar.enc" || { echo "FAIL: plaintext in encrypted tar" >&2; exit 1; }
  else
    [[ "$(head -c 5 "$backup_dir/database.dump")" == "PGDMP" ]] || { echo "FAIL: unexpected dump format" >&2; exit 1; }
  fi

  disposable_down                             # destroy this test project's database and document volumes
  docker compose up -d --wait db api >/dev/null
  empty=$(curl -sf "$API/overview" | jget "['documents']")
  [[ "$empty" == "0" ]] || { echo "FAIL: stack not empty before restore" >&2; exit 1; }

  scripts/restore.sh "$backup_dir" --yes-replace-current-data >/dev/null
  fingerprint > "$WORK/after.json"
  if ! cmp -s "$WORK/before.json" "$WORK/after.json"; then
    echo "FAIL ($label): restored state differs" >&2
    diff <(python3 -m json.tool "$WORK/before.json") <(python3 -m json.tool "$WORK/after.json") | head -40 >&2
    exit 1
  fi
  check_triggers
  echo "PASS ($label): restored state identical (observations, documents = $n); original hashes verified; triggers intact"
}

run_case plaintext
printf 'restore-test-passphrase-%s' "$RANDOM$RANDOM" > "$WORK/passphrase"
export CARDIO_BACKUP_PASSPHRASE_FILE="$WORK/passphrase"
run_case encrypted
