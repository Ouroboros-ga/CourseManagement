# 生产安全配置与恢复

整理：2026-10-19。本文是配置清单，不代表新部署、新安全审计或全部业务验收通过。

## 配置来源

| 仓库文件 | 当前服务器安装位置 |
| --- | --- |
| `deploy/production/course-management.nginx.conf` | `/etc/nginx/sites-available/course-management.conf` |
| `deploy/production/course-management-proxy.conf` | `/etc/course-management/course-management-proxy.conf` |
| `deploy/production/security-headers.conf` | `/etc/course-management/security-headers.conf` |

站点由 `/etc/nginx/sites-enabled/course-management.conf` 链接启用，主配置必须在 nginx `http {}` 中加载。
三个文件已与当前线上配置按换行归一后的 SHA-256 比较一致。本轮补入版本库，不替换线上文件或重启服务。
迁移或换机器时仍需核对域名、证书路径、后端端口、日志路径和完整 include 链。

这些配置包含登录/API/健康接口限流、安全响应头、生产接口文档关闭、敏感路径拦截及不记录查询参数的访问日志。
应用层对应的登录成本、安全头和健康检查变更已经在 `29ea7dd` 入库，不能只恢复 nginx 而遗漏后端版本。

## 修改配置的最低流程

1. 核对当前应用和 Web 发布指针，记录三个实际配置文件及链接状态，备份到仅 root 可读的目录。
2. 审查仓库配置相对于该服务器的差异；证书、私钥、运行环境变量和业务数据不从仓库生成或覆盖。
3. 在明确授权的目标环境安装所需文件。先运行 `nginx -t`；失败时恢复配置，不 reload。
4. 配置通过后才 reload nginx，检查服务状态、首页和 index.html 的安全头、健康接口、静态资源，以及未认证 API 的拒绝行为。
5. 失败时恢复本次修改的配置及链接，再运行 `nginx -t` 后 reload；不要回退数据库或覆盖运行凭证。

只读诊断示例：

```bash
nginx -t
systemctl is-active course-management
readlink -f /opt/course-management/current
readlink -f /opt/course-management/admin-web/current
curl --fail --silent --show-error https://course.zsitai.xyz/health/ready
curl --silent --show-error --head https://course.zsitai.xyz/index.html
```

健康检查只证明进程/数据库就绪，不证明业务权限正确；源码同步需另比发布清单与文件哈希。
`backend.env`、数据库口令、微信 AppSecret、证书私钥和学生材料始终留在受控环境，不入库。

## 历史脚本

2026-10-18 固定版本发布器和验证器保留在 [历史脚本目录](archive/20261018-security-baseline/README.md)。
它们不能直接用于当前发布；当前部署与回滚入口见仓库已有发布工具和 [备份恢复手册](../../docs/RUNBOOK_BACKUP_RESTORE.md)。
扫描工具、原始报告和未核实的 CVE 断言留在本地归档，本轮不发布也不运行。
