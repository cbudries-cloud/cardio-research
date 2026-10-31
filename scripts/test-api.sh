#!/usr/bin/env bash
# API tests on a disposable project with its own Postgres server and volumes, so test setup
# (which drops and recreates the cardio_test database) never runs on the working app's server.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/disposable.sh

export COMPOSE_PROJECT_NAME=cardio-test
use_empty_secrets_dir
export WEB_PORT=${TEST_WEB_PORT:-13300} API_PORT=${TEST_API_PORT:-18300}
trap disposable_down EXIT
disposable_down
docker compose --profile test build -q api-test
if [[ $# -gt 0 ]]; then
  docker compose --profile test run --rm api-test python -m pytest "$@"
else
  docker compose --profile test run --rm api-test
fi
