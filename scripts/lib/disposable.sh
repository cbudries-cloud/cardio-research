# Guards for destructive test operations. Source this file; do not execute it.
#
# Destructive operations (docker compose down -v, dropping databases, restoring over data) in
# test scripts must only ever target a disposable Compose project. The working application runs
# as project "cardio" (override with CARDIO_WORKING_PROJECT) and is never a valid target.

CARDIO_WORKING_PROJECT=${CARDIO_WORKING_PROJECT:-cardio}
DISPOSABLE_PROJECT_PATTERN='^cardio-(test|e2e|restore-test|clean)$'

guard_die() { echo "REFUSED: $*" >&2; exit 97; }

# Validate a project name without touching Docker.
check_disposable_name() {
  local p=${1:-}
  [[ -n "$p" ]] || guard_die "no Compose project name set"
  [[ "$p" != "$CARDIO_WORKING_PROJECT" ]] || guard_die "'$p' is the working application project"
  [[ "$p" =~ $DISPOSABLE_PROJECT_PATTERN ]] || guard_die "'$p' is not a recognized disposable test project"
}

# Validate that the project Compose will actually act on is disposable, and that every volume
# it would delete belongs to that project. Read-only Docker queries only.
require_disposable_project() {
  check_disposable_name "${COMPOSE_PROJECT_NAME:-}"
  local resolved
  resolved=$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
  [[ "$resolved" == "$COMPOSE_PROJECT_NAME" ]] || guard_die "compose resolves to '$resolved', expected '$COMPOSE_PROJECT_NAME'"
  check_disposable_name "$resolved"
  local v owner
  for v in $(docker volume ls -q --filter "label=com.docker.compose.project=$resolved"); do
    owner=$(docker volume inspect -f '{{ index .Labels "com.docker.compose.project" }}' "$v")
    [[ "$owner" == "$resolved" ]] || guard_die "volume $v belongs to '$owner'"
    [[ "$v" == "${resolved}_"* ]] || guard_die "volume $v does not carry the project prefix"
  done
}

# The only way test scripts may delete volumes.
disposable_down() {
  require_disposable_project
  docker compose --profile test --profile e2e down -v --remove-orphans >/dev/null 2>&1 || true
}

# Disposable stacks never mount the participant's API key directory (docs/live-provider-setup.md).
use_empty_secrets_dir() {
  check_disposable_name "${COMPOSE_PROJECT_NAME:-}"
  CARDIO_SECRETS_DIR=$(mktemp -d)
  export CARDIO_SECRETS_DIR
}
