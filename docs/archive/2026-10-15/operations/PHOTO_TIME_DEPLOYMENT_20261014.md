> 历史归档：2026-10-15 整理。原路径：`docs/development/PHOTO_TIME_DEPLOYMENT_20261014.md`。本文保留当时的设计、版本或验收证据，不作为当前实施指令或线上状态。当前资料见[文档导航](../../../README.md)及[最新总体设计](../../../development/CAMPUS_PRODUCT_ARCHITECTURE_WEB_REDESIGN_20261015.md)。正文中的历史日期、命令和测试数字保留原语义。

# 现场照片与北京时间发布验收

2026-10-14，按“部署，通过后提交推送”执行。最终后端和 Web 均为 `20261014-photo-time-r2`，公网入口为 `https://course.zsitai.xyz/`。

## 发布范围与基线

服务器此前实际运行 `20261013-single-review-bbfc72c` 后端及 `20261013-single-review-bbfc72c-preserved` Web，包含另一个协作分支的单次异议审核。当前 Git `dev-main` 尚未合入该分支。为保留线上行为，本次以服务器发布目录为基线，叠加七个后端文件；六个已有文件的原始内容逐一核对与本任务 HEAD 相同。

后端补丁 SHA-256：`20e9b2019779aec1fecc3daa2c9973221496ac3c3a0645863da5ab73faef3275`。最终 Web SHA-256：`9f0640fd2e826349ce11ee30584b9858c43d2e0f8f34210151b26b6cea9e8847`。

Web 保留原静态包及单次审核页面，用 TypeScript AST 精确替换六处异议时间和一处换班申请时间表达式，复用源代码的北京时间函数。更新导入图并使用新的 `pt20261014r2` 资源名，避免一年缓存复用旧内容。其他模块仅重写必要导入引用，原资源保留以兼容已打开页面。没有把工作区整个 dist 或学院升级代码上线。

第一轮 `20261014-photo-time` 通过候选及只读业务检查后，提交前发现新叶子包引用旧入口。新增导入图回归先失败，修复后通过；最终 r2 重新执行候选和线上验收。第一轮并非最终交付版本。

## 本次证据

- 部署前备份：`/var/backups/course-management/20261014T055233Z.ZK55JJ`，含数据库、持久文件、环境及发布指针；root 私有，未下载或提交秘密。
- 候选以服务账号在 `127.0.0.1:18011` 启动，数据库 readiness 通过，临时进程随后停止。
- 候选运行时使用内存 SQLite 构造脱敏账号/任务/照片，HTTP 验证本人列表、字符串 BIGINT ID、访问链接、实际签名下载、他人 404 和解绑 404；不修改生产业务数据。
- 切换后内网及公网 readiness 通过。公网 HTML、入口资源和修改包与磁盘版本逐字节相同；全部新模块引用一致，七处时间调用存在，实际打包函数转换用例通过。
- 当前生产库只读关联查询找到真实本人考勤照片，验证响应装配、所属学生访问判定及真实签名下载。未输出姓名、学号、照片 ID、内容、凭证或签名 URL。
- 本人考勤及文件访问匿名请求均为 401。
- 本地后端 240 passed、Web 9 passed、类型检查和构建通过；新增代码定向 Ruff 通过。既有依赖弃用及 Vite 警告未隐藏。

数据库未执行迁移，原 `181729fc7239` 继续使用。未验证微信真机或浏览器已登录页面的完整交互；真实照片下载、静态时间函数和 HTTP 权限证据不代替这些验收。

## 回退

最终发布目录：`/opt/course-management/releases/20261014-photo-time-r2`、`/opt/course-management/admin-web/releases/20261014-photo-time-r2`。两者的前一指针为 `20261014-photo-time`；原有单次审核目录也完整保留。

若需完整撤销本次热修复，将后端指针原子恢复到 `/opt/course-management/releases/20261013-single-review-bbfc72c`，Web 指针恢复到 `/opt/course-management/admin-web/releases/20261013-single-review-bbfc72c-preserved`，随后重启 `course-management` 并核验 `/health/ready`。本次不修改业务库结构或业务事实，正常回退不需要恢复数据库。

工具为 `deploy/production/build_time_hotfix.mjs`、`test_time_hotfix.mjs`、`deploy_photo_time.py`、`verify_photo_time.py`。部署器绑定本次已核对的基线、目标目录和包摘要，不可当通用脚本直接重跑；发布目录存在或基线变化会拒绝执行。发生切换后验收失败时自动恢复原指针；本次最终验收成功，未触发失败回退。

服务器 `PHOTO_TIME_RELEASE.json` 及 Web `PHOTO_TIME_MANIFEST.json` 保留机器可读证据。本发布是“线上独立基线 + Git 中的任务补丁”，不能声称完整服务等于 `dev-main` 全量构建；后续整包发布前应先合并独立业务分支并演练学院迁移。
