#!/usr/bin/env bash
set -euo pipefail
umask 077
backup=/var/backups/campus-innovation-hub-final-20260930
test -z "$(docker ps -aq --filter name='^campus-final-backup-verify$')"
docker run -d --name campus-final-backup-verify --network none --restart=no \
  --memory=256m --pids-limit=128 --tmpfs /var/lib/postgresql/data:rw,size=192m \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16.2-alpine >/dev/null
trap 'docker rm -f campus-final-backup-verify >/dev/null' EXIT
for attempt in $(seq 1 30); do
  if docker exec campus-final-backup-verify pg_isready -U postgres >/dev/null; then break; fi
  sleep 1
done
# 默认 postgres 角色已由新实例创建；其余角色及所有库按原始全库备份恢复。
gzip -dc "$backup/postgres-all.sql.gz" | sed '/^CREATE ROLE postgres;$/d' \
  | docker exec -i campus-final-backup-verify psql -U postgres -v ON_ERROR_STOP=1 \
  > "$backup/restore-verification.log" 2>&1
count=$(docker exec campus-final-backup-verify psql -U postgres -d campus_innovation_hub_dev \
  -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
test "$count" -gt 0
docker exec campus-final-backup-verify psql -U postgres -d campus_innovation_hub_dev \
  -Atc 'SELECT count(*) FROM django_migrations;' > "$backup/restored-migration-count.txt"
docker exec campus-final-backup-verify pg_dump -U postgres -d campus_innovation_hub_dev -Fc \
  > "$backup/actual-business.dump"
docker exec -i campus-final-backup-verify pg_restore -l < "$backup/actual-business.dump" \
  > "$backup/business-dump-contents.txt"
printf 'All-database restore verified: %s business tables\n' "$count"
cd "$backup"
sha256sum *.gz *.dump *.txt *.json > SHA256SUMS
sha256sum -c SHA256SUMS
