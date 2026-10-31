#!/usr/bin/env bash
# Browser-level end-to-end test against a fresh, isolated stack (separate compose project,
# separate volumes, separate loopback ports). Never touches the development database.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/disposable.sh

export COMPOSE_PROJECT_NAME=cardio-e2e
use_empty_secrets_dir
export WEB_PORT=${E2E_WEB_PORT:-13000}
export API_PORT=${E2E_API_PORT:-18000}
export NOTEBOOK_PORT=${E2E_NOTEBOOK_PORT:-13100}
export CARDIO_ALLOWED_ORIGINS="http://web:3000"
export CARDIO_RESEARCH_PROVIDER=fake  # labelled canned outputs; no network call (D-058)
export CARDIO_LITERATURE_SEARCH=off

trap disposable_down EXIT
disposable_down

docker compose up -d --build --wait db api web notebook
rm -rf tests/end-to-end/test-results
docker compose --profile e2e run --rm e2e
echo "e2e passed. Screenshots: tests/end-to-end/test-results/screens/"
