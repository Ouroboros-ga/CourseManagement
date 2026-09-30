# 校园应用停用记录

2026-09-30，用户明确要求关闭校园应用及其数据库，只保留最后版本作为备份。

- 最后实际运行版本与 current 指针一致：`0b9a6eb6bda5d609211eaea4327f4d73d5b2b9d5`。
- `campus-innovation-hub.service` 已停止并禁用开机自启。
- PostgreSQL 容器 `campus-hub-dev-db` 已停止，restart policy 改为 `no`。当前数据库卷保留，未删除业务数据。
- 校园域名 `zsitai.xyz`、`www.zsitai.xyz` 使用原证书返回 503，不再代理后端或提供前端。8000、5432 不再监听。
- 查课后端公网 readiness 200，原排班站点 200，Nginx 正常。

最终受限备份：`/var/backups/campus-innovation-hub-final-20260930`，约 145MB，root 专用。包含最后版本的完整运行目录、所有 PostgreSQL 数据与角色、冷数据库卷、上传文件、服务/环境/Nginx/TLS 配置、容器参数和 SHA256 清单。早期 Judge0 持久数据备份并入此归档，避免丢失历史持久数据，不保留其旧应用源码版本。

容器默认数据库是 `postgres`，实际业务库为 `campus_innovation_hub_dev`。最初默认库 custom dump 是空库；完整 `postgres-all.sql.gz` 覆盖实际业务。完整备份已在无网络、无持久卷的临时 PostgreSQL 16.2 实例中恢复，验证 37 张业务表和迁移表，并重新生成 `actual-business.dump`。临时验证容器已销毁，原数据库保持停止。

仅保留最后版本目录 `/opt/campus-innovation-hub/releases/0b9a6eb6bda5d609211eaea4327f4d73d5b2b9d5`，清理旧发布、开发、阶段测试目录以及已并入最终归档的旧备份目录。具体路径保存在最终备份的 `removed-history.json`。清理脚本逐一确认目标绝对路径、父目录和非符号链接；未操作 CourseManagement 或 course-scheduler 路径。

需要恢复时，先检查端口与资源，再启动保留的 PostgreSQL 容器，恢复归档中的原 Nginx 站点文件并 `nginx -t`，启动校园服务。原配置和数据库卷保持原位；恢复前先评估是否影响当前运行的查课系统，不直接执行重启全机或覆盖现有数据。

本备份仍为同机备份，未制作异机副本；此次停用不代表已验证全部校园应用业务功能。
