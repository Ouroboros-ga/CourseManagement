# 后端首次上线记录

2026-09-30，主机 `120.26.32.241`，Ubuntu 22.04。用户确认新建空库、管理员账号 `admin`，提供 `course.zsitai.xyz` 证书并确认 DNS A 记录。

## 入口与运行配置

- API 根地址：`https://course.zsitai.xyz/api/v1`。健康检查：`https://course.zsitai.xyz/health/ready`。本站仅部署后端，根路径没有管理端页面；`/docs` 和公网 `/openapi.json` 关闭。
- Nginx 独立站点 `/etc/nginx/sites-available/course-management.conf`，HTTP 跳 HTTPS，上传请求体限制 12MB。原有两个应用与站点保留，原排班站点实测 200。
- Python 3.12.13，单进程非 root systemd 服务 `course-management.service`，内部 `127.0.0.1:8011`。服务账号 `course-management`；内存上限 384MB；登录入口每 IP 10 次/分钟、burst 10，并限制全站同时口令登录 2 个。
- 发布目录 `/opt/course-management/releases/20260930-02`；`/opt/course-management/current` 指向该目录；持久文件目录 `/var/lib/course-management/files`。
- 运行配置 `/etc/course-management/backend.env`，root 所有、0600。运行日志 `journalctl -u course-management`；Nginx 访问日志不记录查询参数，Uvicorn 访问日志关闭。
- 数据库容器 `course-management-mysql`，仅监听 `127.0.0.1:13308`，数据 `/var/lib/course-management/mysql`。MySQL 8.4.8 经备用镜像代理下载，固定摘要 `sha256:2952e3be7807f06fc18de50b3ea1a632d5c70d63482ff7d7376fe3aa8999babf`。限制 40 连接、128MiB buffer pool、关闭 performance_schema；容器内存上限 512MB。
- 新空库迁移至 `d42a9e6c71b0`，43 张表，初始化 5 角色、40 权限和 `admin` 超级管理员；没有导入真实学生资料或演示数据。
- 运行账号逐表 CRUD，审计表仅 SELECT/INSERT，无 DDL 权限；迁移凭证独立保存在 `/etc/course-management/migration.env`。

## 发布与验收证据

114 个后端源码文件与上轮验收指纹一致，`uv lock --check` 通过。最终运行包 SHA256：`b03a9b47769ee2183ceb0f967fbf66eeb96487def96c43c45c5ed7f82cccc84a`。

官方源下载缓慢，使用 `uv export --frozen --no-dev --no-emit-project` 导出运行依赖，在国内源以 `--require-hashes` 安装 39 个锁定依赖；业务代码在后端工作目录导入，没有将项目以 editable 包安装。第一次打包缺 README 的未启用目录保留作为诊断记录，正式运行的是 `20260930-02`。

Windows tar 文件权限在服务器规范化为目录 0755、文件 0644，避免服务用户改写代码，以及 MySQL 忽略 world-writable 配置。实际运行配置值已 SQL 核验。

已完成：

- 本机通过实际 DNS/TLS 请求公网 readiness，返回 200、database=up；HTTP 跳转 301。
- 真实 HTTPS 登录成功，刷新凭证不在 JSON 内，Cookie 包含 Secure/HttpOnly/SameSite=Lax/Path。
- 未登录读取 401，认证后本人资料及学期列表读取 200；非法 Origin 刷新 403；合法刷新成功、登出后原凭证 401。
- 服务重启后重复上述验证通过，开机自启已启用；MySQL 重启恢复通过。未重启整个宿主机。
- 运行账号审计 UPDATE 和 CREATE TABLE 测试均返回 MySQL 1142，未写业务数据。
- Nginx 配置检查通过；后端重启次数 0、MySQL 未 OOM，日志未发现异常堆栈。
- 首次数据库与材料备份通过 SHA256 校验；恢复到专用空演练库，核验 43 表、迁移头、管理员和权限注册表后删除演练库。材料目录目前为空，真实材料恢复尚未演练。

此轮没有重新运行此前完整业务回归；上线验证针对与已验收源码一致的 Linux 运行环境。未做正式并发/容量压测。

## 账号与运维

管理员用户名 `admin`，密码由服务器生成，保存在 root 专用 `/etc/course-management/initial-admin.env`。用户可在自己的终端执行：

```bash
ssh root@120.26.32.241 'cat /etc/course-management/initial-admin.env'
```

取等号后的值登录。初始账号是 bootstrap 超级管理员，可继续创建教师账号；不得将该文件发到公开渠道。口令不在本仓库、发布包、对话或应用日志中。

```bash
systemctl status course-management
journalctl -u course-management -n 100 --no-pager
docker logs --tail 100 course-management-mysql
bash /opt/course-management/backup.sh
```

每日备份 timer `course-management-backup.timer` 在上海时间约 03:15–03:20 运行，目录 `/var/backups/course-management`，root 专用。备份包括数据库、材料、运行配置和发布指针；磁盘保留空间不足时失败，不自动删除历史备份。备份目前同机，仍需异机副本及明确留存策略。在线数据库与文件归档不是跨存储原子快照，真实写入条件下须另验证一致性。

## 业务参数和剩余事项

- 已沿用周任务上限 3；每日截止时间 22:00 是首次种子默认，管理端每日配置可覆盖。
- 照片/证明保留期分别有独立配置，目前技术默认均 180 天；周报文件 365 天、临时文件 1 天、导入文件 30 天。尚需业务确认，未启用自动到期删除定时器。保留期会在上传时固化并影响访问，到期清理不开启不代表材料永不过期。
- 微信登录暂关闭，尚需正式 AppID/AppSecret；管理端若跨域部署，需要精确增加 CORS/CSRF 来源。目前为本域同源配置。
- 用户证书到期 `2026-12-28 23:59:59 UTC`，为手动提供证书，未配置自动续签。
- 当前主机 2 核、约 1.6GiB 内存，并承载其他服务；最终可用内存约 417MB、磁盘约 5.9GB。需正式容量压测与磁盘扩容规划，不能据此宣称已支持 900 人并发。
- 首次发布无旧 CourseManagement 版本可回退。撤回本站时先停 `course-management`，移除仅本站启用链接，`nginx -t` 后 reload；保留数据库、材料、备份和配置，不删除数据。后续发布迁移前先备份；应用切换与数据库回退必须分别评估，不能盲目 downgrade。

部署脚本见 `deploy/production/`。`prepare_server.py` 和 `activate_first_release.sh` 仅供已确认的首次空库初始化，拒绝已有状态；后续发布不能直接重跑。
