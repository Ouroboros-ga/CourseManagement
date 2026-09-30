#!/usr/bin/env bash
# 用户授权停用校园应用，只保留最后实际版本及其数据；不操作查课和排班目录。
set -euo pipefail
umask 077
base=/opt/campus-innovation-hub
last=/opt/campus-innovation-hub/releases/0b9a6eb6bda5d609211eaea4327f4d73d5b2b9d5
backup=/var/backups/campus-innovation-hub-final-20260930
test "$(readlink -f "$base/current")" = "$last"
test "$(readlink -f /proc/$(systemctl show campus-innovation-hub -p MainPID --value)/cwd)" = "$last/backend"
test ! -e "$backup"
install -d -m 0700 "$backup"
printf '%s\n' "$last" > "$backup/release.txt"
docker inspect campus-hub-dev-db > "$backup/database-container.json"
systemctl cat campus-innovation-hub > "$backup/service.txt"
tar -czf "$backup/configuration.tar.gz" -C / \
  etc/campus-innovation-hub etc/ssl/campus-innovation-hub \
  etc/systemd/system/campus-innovation-hub.service \
  etc/nginx/sites-available/campus-innovation-hub.conf \
  etc/nginx/snippets/campus-proxy-headers.conf \
  etc/nginx/snippets/campus-admin-allow.conf
# 全站关闭，但保留域名和证书返回 503，避免落到其他应用默认站点。
cat > /etc/nginx/sites-available/campus-innovation-hub.conf <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name zsitai.xyz www.zsitai.xyz;
    return 503;
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name zsitai.xyz www.zsitai.xyz;
    ssl_certificate /etc/ssl/campus-innovation-hub/zsitai.xyz.pem;
    ssl_certificate_key /etc/ssl/campus-innovation-hub/zsitai.xyz.key;
    return 503;
}
NGINX
nginx -t
systemctl reload nginx
systemctl disable --now campus-innovation-hub
# 应用已停止写入，再获取所有数据库和角色的逻辑备份。
docker exec campus-hub-dev-db sh -c 'exec pg_dumpall -U "$POSTGRES_USER"' \
  | gzip > "$backup/postgres-all.sql.gz"
docker exec campus-hub-dev-db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$backup/application.dump"
docker exec -i campus-hub-dev-db pg_restore -l < "$backup/application.dump" > "$backup/dump-contents.txt"
gzip -t "$backup/postgres-all.sql.gz"
# 停止数据库，保存一致的冷卷，同时禁用 Docker 自动重启。
docker update --restart=no campus-hub-dev-db >/dev/null
docker stop campus-hub-dev-db
tar -czf "$backup/postgres-volume.tar.gz" -C /var/lib/docker/volumes/campus-hub-dev-postgres/_data .
tar -czf "$backup/latest-release.tar.gz" -C "$base/releases" "$(basename "$last")"
tar -czf "$backup/application-data.tar.gz" -C /var/lib campus-innovation-hub
# 小体积早期 Judge0 数据备份并入唯一归档，避免丢失历史持久数据；不保留旧应用版本。
if test -d /opt/backups/campus-innovation-hub; then
  tar -czf "$backup/legacy-component-data.tar.gz" -C /opt/backups campus-innovation-hub
fi
cd "$backup"
for archive in *.tar.gz; do tar -tzf "$archive" >/dev/null; done
sha256sum *.gz application.dump release.txt database-container.json service.txt dump-contents.txt > SHA256SUMS
sha256sum -c SHA256SUMS
printf 'Backup verified: %s\n' "$backup"
