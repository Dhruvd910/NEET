#!/usr/bin/env sh
# Nightly backup: PostgreSQL dump + stored source files. Run from the repository root via cron, e.g.
#   15 2 * * * cd /srv/neet && sh deploy/backup.sh >> /var/log/neet-backup.log 2>&1
# Copy BACKUP_DIR off the host (object storage with encryption at rest), and test a restore monthly.
set -eu
COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env"
BACKUP_DIR=${BACKUP_DIR:-/var/backups/neet}
KEEP_DAYS=${KEEP_DAYS:-14}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"

$COMPOSE exec -T db pg_dump -U neet -d neet --format=custom > "$BACKUP_DIR/db-$STAMP.dump"
$COMPOSE exec -T api tar -C /data -czf - storage > "$BACKUP_DIR/storage-$STAMP.tar.gz"

# Retention: deleted accounts disappear from backups after KEEP_DAYS (state this in the privacy notice).
find "$BACKUP_DIR" -type f -mtime +"$KEEP_DAYS" -delete
echo "backup $STAMP ok"
