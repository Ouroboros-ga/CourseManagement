#!/usr/bin/env bash
# root 专用；在线逻辑备份与文件归档，不宣称跨存储事务一致性。
# 尚未确认备份留存期，不自动删除历史备份；应另安排异机备份。
set -euo pipefail
umask 077
install -d -m 0700 /var/backups/course-management
exec 9>/var/backups/course-management/backup.lock
flock -n 9 || exit 0
available=$(df -B1 --output=avail /var/backups/course-management | tail -1 | tr -d ' ')
storage=$(du -sb /var/lib/course-management/files /var/lib/course-management/mysql | awk '{sum+=$1} END {print sum}')
if (( available < storage + 1073741824 )); then
  echo 'Insufficient disk reserve for backup; expand storage or review retention' >&2
  exit 1
fi
backup=$(mktemp -d "/var/backups/course-management/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
docker exec course-management-mysql mysqldump --defaults-extra-file=/run/cm-root.cnf \
  --single-transaction --quick --no-tablespaces --set-gtid-purged=OFF course_management \
  | gzip > "$backup/database.sql.gz"
tar -czf "$backup/files.tar.gz" -C /var/lib/course-management files
cp /etc/course-management/backend.env "$backup/backend.env"
readlink /opt/course-management/current > "$backup/release.txt"
cd "$backup"
sha256sum database.sql.gz files.tar.gz backend.env release.txt > SHA256SUMS
printf 'Backup completed: %s\n' "$backup"
