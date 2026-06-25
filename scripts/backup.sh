#!/usr/bin/env bash
# Dump the Postgres database to a timestamped gzip file.
# Usage:  ./scripts/backup.sh [backup_dir]
# Cron (daily 03:00):
#   0 3 * * * cd /opt/books_store_bot && ./scripts/backup.sh >> backups/backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${1:-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$BACKUP_DIR"

# Load DB_* from .env
set -a; [ -f .env ] && . ./.env; set +a
DB_USER="${DB_USER:-books}"
DB_NAME="${DB_NAME:-books_store}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/${DB_NAME}_${STAMP}.sql.gz"

docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$OUT"
echo "$(date '+%F %T')  backup -> $OUT ($(du -h "$OUT" | cut -f1))"

# Prune old backups
find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +"$KEEP_DAYS" -delete
