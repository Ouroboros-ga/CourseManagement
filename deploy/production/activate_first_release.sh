#!/usr/bin/env bash
# 首次空库上线；仅在 prepare_server.py 成功且镜像/依赖安装完成后运行。
set -euo pipefail
umask 077
release=/opt/course-management/releases/20260930-02
cd "$release/backend"
test -x .venv/bin/uvicorn
# Windows tar 可携带 0666/0777；源码不可由服务账号改写，MySQL 拒绝 world-writable 配置。
find "$release" -path '*/.venv' -prune -o -type d -exec chmod 755 {} \; -o -type f -exec chmod 644 {} \;
test ! -e /opt/course-management/current
image=docker.m.daocloud.io/library/mysql@sha256:2952e3be7807f06fc18de50b3ea1a632d5c70d63482ff7d7376fe3aa8999babf
docker image inspect "$image" >/dev/null
test -z "$(docker ps -aq --filter name='^course-management-mysql$')"
install -d -m 0700 /var/lib/course-management/mysql
docker run -d --name course-management-mysql --restart unless-stopped \
  --memory 512m --memory-swap 768m --pids-limit 256 \
  --env-file /etc/course-management/mysql.env \
  -p 127.0.0.1:13308:3306 \
  -v /var/lib/course-management/mysql:/var/lib/mysql \
  -v "$release/deploy/production/mysql.cnf:/etc/mysql/conf.d/course-management.cnf:ro" \
  -v /etc/course-management/mysql-root.cnf:/run/cm-root.cnf:ro \
  "$image"
for attempt in $(seq 1 90); do
  if docker exec course-management-mysql mysql --defaults-extra-file=/run/cm-root.cnf \
    -Nse 'SELECT 1' >/dev/null 2>&1; then break; fi
  sleep 2
done
docker exec course-management-mysql mysql --defaults-extra-file=/run/cm-root.cnf -Nse 'SELECT 1'
set -a
source /etc/course-management/backend.env
source /etc/course-management/migration.env
set +a
.venv/bin/alembic upgrade head
.venv/bin/alembic current
set -a
source /etc/course-management/initial-admin.env
set +a
.venv/bin/python -m app.modules.identity.seed --admin-username admin
unset SEED_ADMIN_PASSWORD
docker exec -i course-management-mysql mysql --defaults-extra-file=/run/cm-root.cnf \
  < /etc/course-management/runtime-user.sql
# 用逐表授权排除审计表的 UPDATE/DELETE；数据库级授权无法用表级撤销覆盖。
docker exec course-management-mysql mysql --defaults-extra-file=/run/cm-root.cnf \
  -e "REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'cm_runtime'@'%';"
docker exec course-management-mysql mysql --defaults-extra-file=/run/cm-root.cnf -Nse \
  "SELECT CONCAT('GRANT ', IF(TABLE_NAME='audit_log','SELECT, INSERT','SELECT, INSERT, UPDATE, DELETE'), ' ON course_management.', TABLE_NAME, ' TO ', CHAR(39), 'cm_runtime', CHAR(39), '@', CHAR(39), '%', CHAR(39), ';') FROM information_schema.TABLES WHERE TABLE_SCHEMA='course_management' AND TABLE_TYPE='BASE TABLE';" \
  | docker exec -i course-management-mysql mysql --defaults-extra-file=/run/cm-root.cnf
ln -s "$release" /opt/course-management/current
systemctl daemon-reload
systemctl enable --now course-management.service
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8011/health/ready; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:8011/health/ready
