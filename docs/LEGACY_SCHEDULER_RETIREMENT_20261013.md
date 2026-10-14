# 旧排课服务停用记录

后续更新（2026-10-13）：现 `http://vol.zsitai.xyz/` 返回 302 到 `https://course.zsitai.xyz/`，跟随跳转返回 200。原 410 配置备份于 `/var/backups/course-scheduler-source/vol-redirect-before-20261013T151516Z.conf`。Nginx 和新服务健康检查通过；下方 410 是停用当时的历史记录。旧域名无 HTTPS 证书，本次只改原 HTTP 入口，目标服务使用现有 HTTPS。

2026-10-13，用户要求确认旧服务、保留源码备份后删除代码和数据；确认没有配套 GitHub 仓库后，改为仅在服务器保留源码备份，不上传 GitHub。

- 旧服务：`course-scheduler.service`，Streamlit `127.0.0.1:8501`，域名 `http://vol.zsitai.xyz/`。
- 原活动版本：`20260918-224546`；共保留七个历史发布版本、224 个源码文件，逐文件 SHA-256 对账及 Python 语法检查通过。
- 服务器备份：`/var/backups/course-scheduler-source/20261013T150836Z/`，root 私有权限；含 `source.tar.gz`、`SOURCE_MANIFEST.json`（压缩包内）、`SHA256SUMS`、历史 systemd/Nginx 配置、`RESTORE.md` 和 `RETIREMENT.json`。
- 压缩包 477,380 字节（约 466 KiB），完整备份目录磁盘占用约 500 KiB。SHA-256：`a87123bef1438a23ad1f7126349b3d1cf88197ebb2056884259684ab5c662203`。
- 删除的专属目录：`/opt/course-scheduler`、`/var/lib/course-scheduler`、`/var/backups/course-scheduler`。运行数据库、登录凭证、会话和历史数据备份已删除；源码备份不能恢复业务记录。
- 服务已停止、禁用并移除 unit 及旧 unit 备份，8501 无监听。删除旧 IP 跳转配置，旧域名保留独立 410 停用响应，避免误落入其他站点。
- 本次观察磁盘可用空间增加 679,129,088 字节，约 648 MiB；可能包含同时发生的系统磁盘变化。
- 最终核验：服务器 `sha256sum -c SHA256SUMS` 为 OK；公网旧域名返回 410；`https://course.zsitai.xyz/health/ready` 返回数据库 up。当前查课系统版本、配置和业务数据未改动。

恢复代码时先核对 SHA256SUMS，将压缩包解到独立目录，使用原活动版本及锁文件建立新环境。配置文件仅作历史参考，不自动恢复服务；重新开放须另行确认。此次备份在同一服务器，不属于异机灾备。

本地另保留 Git 忽略的源码副本、哈希清单及非敏感执行记录于 `tmp/scheduler-retirement/`。没有把运行数据或凭证带回开发机。
