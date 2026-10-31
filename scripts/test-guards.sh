#!/usr/bin/env bash
# Checks the destructive-operation guards without running any destructive command.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
expect() {  # expect <refuse|allow> <project-name>
  local want=$1 name=$2 out
  out=$(bash -c "source scripts/lib/disposable.sh; check_disposable_name '$name'" 2>&1); local rc=$?
  if [[ $want == refuse && $rc -eq 97 ]] || [[ $want == allow && $rc -eq 0 ]]; then
    echo "ok   $want '$name'"
  else
    echo "FAIL expected $want for '$name' (rc=$rc) $out"; fail=1
  fi
}
expect refuse ""
expect refuse "cardio"
expect refuse "cardio-prod"
expect refuse "cardio_test"
expect refuse "something-else"
expect allow  "cardio-test"
expect allow  "cardio-e2e"
expect allow  "cardio-restore-test"

# Resolved-project check: pointing COMPOSE_PROJECT_NAME at a disposable name while the compose
# file would resolve elsewhere must be refused (read-only `docker compose config`).
out=$(COMPOSE_PROJECT_NAME=cardio-e2e bash -c 'source scripts/lib/disposable.sh; docker() { if [[ $1 == compose ]]; then echo "{\"name\": \"cardio\"}"; else command docker "$@"; fi; }; require_disposable_project' 2>&1); rc=$?
[[ $rc -eq 97 ]] && echo "ok   refuse when compose resolves to the working project" || { echo "FAIL resolved-name guard ($rc) $out"; fail=1; }

# Every destructive script must route volume deletion through the guard.
for f in scripts/e2e.sh scripts/test-backup-restore.sh scripts/test-api.sh; do
  if grep -nE 'down[^|]*-v' "$f" | grep -v disposable_down >/dev/null; then echo "FAIL $f deletes volumes without the guard"; fail=1; else echo "ok   $f uses disposable_down"; fi
done
grep -q 'CARDIO_RESTORE_TEST' scripts/restore.sh && echo "ok   restore.sh checks test mode" || { echo "FAIL restore.sh guard missing"; fail=1; }

# Working-app volumes must be untouched by this check.
docker volume inspect cardio_pgdata cardio_documents >/dev/null 2>&1 && echo "ok   working volumes present" || echo "note working volumes not present (stack not started)"
exit $fail
