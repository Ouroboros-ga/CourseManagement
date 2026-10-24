> 归档说明（2026-10-24）：原路径 `docs/development/STAFF_TEMPORARY_ONBOARDING_RELEASE.md`。本文保留当时的计划、验证或发布事实，不代表当前部署状态；后续执行请看[当前实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 教职工临时工号发布记录

日期：2026-10-19。目标：`101.34.52.163`，测试入口：[test.zsitai.xyz](https://test.zsitai.xyz)。本次 DNS 核对：该测试域名指向 `101.34.52.163`；`course.zsitai.xyz` 仍指向 `120.26.32.241`，后者不属于本次发布目标。

## 代码与运行版本

- 功能提交：`a6db3fe47c4b34483ead33cbda44eab7d22404b1`，已推送 `origin/dev-main`。
- 后端 current：`/opt/course-management/releases/20261019-staff-onboarding-a6db3fe47c`。
- 原后端及回滚目标：`/opt/course-management/releases/20261019-member-onboarding-fe626e3d9d`。
- Web 保持：`/opt/course-management/admin-web/releases/20261019-member-onboarding-fe626e3d9d`；小程序源码及配置未发布变更。
- 数据库由 `f26a1019d001` 升至 `f26a1019s007`。核验 `temporary_staff_no` 为可空 `varchar(64)`，唯一索引列顺序为 `school_id, temporary_staff_no`。

新服务器的健康检查、配置及 OSS 存储适配在发布前已不同于旧 Git 发布提交，本次逐项核对并原样保留，不将其覆盖为本地版本。三份文件及哈希记入运行清单 `preserved_live_overrides/runtime_files`；因此运行版本是功能提交加以下既有服务器适配：

| 文件 | SHA-256 |
| --- | --- |
| `backend/app/api/health.py` | `ebb77e4fe602b360c50c2fb32cc1906c48ca653c2d92cdd0f6cd5072063dde73` |
| `backend/app/core/config.py` | `945624195eddfeddfce5f54b6beb41f212730c6cbdc4a585329185fca7fbccf1` |
| `backend/app/modules/file/storage.py` | `88ae93d6fb1a884cbcfcdf228b854bb28ac6a8753c10a918055b1fe17a4a193e` |

## 发布与验证证据

提交前复验：**102 passed / 1 skipped**，跳过的 MySQL 并发用例已有独立 MySQL 通过证据，见 [本地验收](../reviews/STAFF_TEMPORARY_ONBOARDING_ACCEPTANCE.md)。本次定向 ruff、mypy、Alembic head 和差异检查通过。

上线过程：检查前置版本和源码哈希 → 数据库及文件备份并核验 → 提取已推送 Git 提交的后端包 → 保留三份服务器适配 → 复制并修正独立虚拟环境 → 增量迁移 → 服务用户运行后台 CLI 帮助检查 → `127.0.0.1:18021` 候选服务就绪和匿名授权检查 → 原子切换后端 current → 重启并核验正式服务。

- 正式服务 `course-management` active；`127.0.0.1:8011/health/ready` 与公网就绪正常，`database=up`。
- 从本机使用 TLS 校验并以 `--resolve course.zsitai.xyz:443:101.34.52.163` 明确定向新 IP：健康成功；匿名 `/api/v1/me` 和 `/api/v1/me/inspection-records?view=teaching` 均 **401**。另通过正常 DNS 访问 `https://test.zsitai.xyz/health/ready` 成功。
- 独立脚本逐个验证 **537 个运行文件** SHA-256，实际迁移字段/唯一索引通过。`nginx -t` 通过，配置和 Web 指针未改变。
- 公网首页 SHA-256：`17b7efa4abf2f9387427326b2d4e7b9ba3582750c2cc272e16c838c4f5a75c6e`；入口脚本 `/assets/index--aqYh9bv.js` SHA-256：`0db28df85130a65375f1cdc31dae34994e40373c70ea7f6c78962e146723a6d0`。均与服务器当前 Web 文件一致。
- 发布前后 `faculty_staff / teaching_staff_assignment / class_staff_responsibility / administrative_class / student / course_schedule` 均为 0。未 seed、未导入真实教务资料、未建教师账号或档案、未签发真实绑定码。

## 备份及回滚

备份目录：`/var/backups/course-management/20261019T091013Z.Ysn3Mq`。包含数据库压缩备份、文件归档、环境配置备份、旧指针，以及部署脚本、发布清单、报告、核验和回滚脚本。`SHA256SUMS` 与 `RELEASE_SHA256SUMS` 均已核验。

服务器当前发布根目录 `RELEASE.json` 及备份目录 `report.json` 保存运行哈希、前后版本、配置指纹、候选和正式匿名授权、业务表数量及备份位置。备份目录的 `rollback_release.py` 默认为只打印计划，显式 `--apply` 才切回旧后端并重启、核验就绪。

```bash
/opt/course-management/current/backend/.venv/bin/python \
  /var/backups/course-management/20261019T091013Z.Ysn3Mq/rollback_release.py --apply
```

回滚仅恢复旧应用，保留可兼容的新增字段；不降级或恢复数据库，不更改 Web 和配置。回滚脚本已检查用法与前置版本，未实际执行回滚。

## 下一步测试

在测试入口导入真实课表和行政班资料后，按 [操作说明](../../../development/STAFF_TEMPORARY_ONBOARDING.md) 后台提取候选、核对建档并导出绑定码。责任表缺少档案导致原导入无法确认时，可作为后台 `--responsibility-file` 输入。不自动把上传姓名变成教师权限。

生产 CLI 需加载 `/etc/course-management/backend.env`，使用当前发布自身 Python 并以受控运维方式执行；输入操作者和学院 ID 必须来自实际授权。候选名单和凭证写入私有目录，不放进静态站点。

尚未验证真实教务数据导入、教师微信真实登录、绑定及真机业务操作；上述测试由真实资料和教师参与后完成。本次未改小程序默认后端地址，测试设备须确认使用测试服务入口。
