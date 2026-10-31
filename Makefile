# Documented entry points. Every target runs in Docker; see README.md.
.PHONY: up down logs test guard-test e2e backup verify-backup restore-test schemas fixtures research-charts research-validate notebook check

up:            ## Build and start the local stack (http://127.0.0.1:3000)
	docker compose up -d --build --wait

down:          ## Stop the stack (data volumes are kept)
	docker compose down

logs:
	docker compose logs -f api web

test:          ## API unit/integration tests on a disposable project (own Postgres, own volumes)
	./scripts/test-api.sh

guard-test:    ## Verify destructive-operation guards (no destructive commands are run)
	./scripts/test-guards.sh

e2e:           ## Browser-level workflow test on an isolated stack
	./scripts/e2e.sh

restore-test:  ## Backup-and-restore test on an isolated stack (plaintext and encrypted)
	./scripts/test-backup-restore.sh

backup:        ## Back up the running stack to $$CARDIO_BACKUP_DIR (default ~/cardio-research-data/backups)
	./scripts/backup.sh

verify-backup: ## Restore BACKUP=<dir> into a disposable project and compare digests with the working stack
	./scripts/verify-backup.sh $(BACKUP)

schemas:       ## Export the API contract to packages/schemas/openapi.json
	docker compose --profile test build -q api-test
	docker compose --profile test run --rm --no-deps -T api-test python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))" > packages/schemas/openapi.json

fixtures:      ## Regenerate synthetic fixtures
	docker compose --profile test run --rm --no-deps -v "$$PWD/fixtures:/out" api-test python /out/synthetic/generate.py /out/synthetic

research-charts: ## Regenerate chart-input CSVs from chart specs and evidence claims
	docker compose --profile test build -q api-test
	docker compose --profile test run --rm --no-deps -v "$$PWD/research:/research" -e PYTHONPATH=/packages/evidence-tools api-test python -m evidence_tools.charts /research

research-validate: ## Validate research/ (add SOURCE_CACHE=<dir> to check quotes against cached full texts)
	docker compose --profile test build -q api-test
	docker compose --profile test run --rm --no-deps $(if $(SOURCE_CACHE),-v "$(SOURCE_CACHE):/cache:ro",) -e PYTHONPATH=/packages/evidence-tools api-test python -m evidence_tools.validate /research $(if $(SOURCE_CACHE),--source-cache /cache,) $(if $(ONLY),--only $(ONLY),)

notebook:      ## Build and start only the research notebook (http://127.0.0.1:3100)
	docker compose up -d --build --wait notebook

check: guard-test test e2e restore-test  ## Everything required by the Milestone 1-2 acceptance criteria
