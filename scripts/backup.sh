#!/usr/bin/env bash
# Back up the database and original documents of the running stack.
#
#   scripts/backup.sh                       -> $CARDIO_BACKUP_DIR/<UTC timestamp>/
#
# Backups contain health records. They are written OUTSIDE the repository
# (default ~/cardio-research-data/backups). If CARDIO_BACKUP_PASSPHRASE_FILE points to a
# file containing a passphrase, both artifacts are encrypted with openssl (AES-256-CBC,
# PBKDF2). Without it, backups are plaintext and rely on host disk encryption
# (see docs/safety-boundaries.md).
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_ROOT=${CARDIO_BACKUP_DIR:-$HOME/cardio-research-data/backups}
case "$(cd "$(dirname "$BACKUP_ROOT")" 2>/dev/null && pwd)/" in
  "$(pwd)/"*) echo "Refusing to write backups inside the repository." >&2; exit 1 ;;
esac

ts=$(date -u +%Y%m%dT%H%M%SZ)
dest="$BACKUP_ROOT/$ts"
umask 077
mkdir -p "$dest"

encrypt() {  # stdin -> stdout
  if [[ -n "${CARDIO_BACKUP_PASSPHRASE_FILE:-}" ]]; then
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$CARDIO_BACKUP_PASSPHRASE_FILE"
  else
    cat
  fi
}
suffix=""
[[ -n "${CARDIO_BACKUP_PASSPHRASE_FILE:-}" ]] && suffix=".enc"

docker compose exec -T db pg_dump -U cardio -d cardio --format=custom | encrypt > "$dest/database.dump$suffix"
docker compose exec -T api tar -C /data/documents -cf - . | encrypt > "$dest/documents.tar$suffix"

revision=$(docker compose exec -T db psql -U cardio -d cardio -Atc "select version_num from alembic_version")
observations=$(docker compose exec -T db psql -U cardio -d cardio -Atc "select count(*) from observations")
documents=$(docker compose exec -T db psql -U cardio -d cardio -Atc "select count(*) from source_documents")
cat > "$dest/MANIFEST" <<EOF
created_utc=$ts
schema_revision=$revision
observations=$observations
source_documents=$documents
encrypted=$([[ -n "$suffix" ]] && echo yes || echo no)
EOF
(cd "$dest" && shasum -a 256 "database.dump$suffix" "documents.tar$suffix" MANIFEST > SHA256SUMS)
echo "$dest"
