#!/usr/bin/env bash
# 首次上线恢复演练：只创建、校验并删除本脚本自己的隔离库，拒绝同名已有库。
set -euo pipefail
database=course_management_restore_20260930
container=course-management-mysql
backup=${1:?Specify backup directory}
sql() { docker exec "$container" mysql --defaults-extra-file=/run/cm-root.cnf -Nse "$1"; }
test "$(sql "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='$database';")" = 0
cd "$backup"
sha256sum -c SHA256SUMS
sql "CREATE DATABASE $database CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
trap 'sql "DROP DATABASE course_management_restore_20260930;"' EXIT
gzip -dc database.sql.gz | docker exec -i "$container" mysql --defaults-extra-file=/run/cm-root.cnf "$database"
source_tables=$(sql "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='course_management';")
restore_tables=$(sql "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$database';")
test "$source_tables" = "$restore_tables"
test "$(sql "SELECT version_num FROM $database.alembic_version;")" = d42a9e6c71b0
test "$(sql "SELECT COUNT(*) FROM $database.user_account;")" = 1
test "$(sql "SELECT COUNT(*) FROM $database.role;")" = 5
test "$(sql "SELECT COUNT(*) FROM $database.permission;")" = 40
tar -tzf files.tar.gz >/dev/null
printf 'Restore verified: %s tables, migration head, admin and permission registry; isolated database removed on exit\n' "$restore_tables"
