# 2026-10-13 开发技能检索结果

## 已安装并使用

用户所称 findskill 对应 Vercel Labs 的 **find-skills**。已通过 Codex skill-installer 从 `vercel-labs/skills` 安装到 `C:/Users/LIU/.codex/skills/find-skills/`，核对 SKILL.md 后实际使用 `npx.cmd --yes skills find` 搜索。

- [来源与使用说明](https://github.com/vercel-labs/skills/blob/main/skills/find-skills/SKILL.md)
- 先查看 skills.sh 榜单，再检索 `vue`、`fastapi`、`sqlalchemy`、`mysql`、`authorization`、`wechat`、`systematic debugging`、`miniprogram`。
- 已核对候选内容、来源、平台展示的安装量与 GitHub stars。数量为当日近似值，热度不等于质量或本项目适配性。
- 首轮只安装 find-skills；用户随后授权补充以下六项，现已安装并核对 SKILL.md。业务代码未因技能安装而修改。

## 最适用的候选

| 技能与来源 | 近似安装量 | 适用于当前项目的工作 | 使用边界 |
| --- | --- | --- | --- |
| [auth-implementation-patterns / wshobson/agents](https://skills.sh/wshobson/agents/auth-implementation-patterns) | 18.2K | 身份绑定、角色生命周期、会话、RBAC 与资源归属；对应 B01/B02/B05 | 保留已有会话回查、Argon2 和本人资源范围，不照抄简化 JWT 示例替换它们 |
| [mysql / planetscale/database-skills](https://skills.sh/planetscale/database-skills/mysql) | 8.3K | 导入事务、锁序、索引、迁移及真实 MySQL 验证；对应 B03/B06/B07/B08 | 使用现有自建 MySQL，不因技能中的托管推广改变部署；Session/rollback 仍需核对实际 SQLAlchemy 代码 |
| [vue-best-practices / vuejs-ai/skills](https://skills.sh/vuejs-ai/skills/vue-best-practices) | 40.9K | Composition API、明确数据流、组件/composable 职责和复杂页面维护 | 用于本项目 Vue 3；组件拆分按实际收益决定，先修正确性 |
| [vue-testing-best-practices / vuejs-ai/skills](https://skills.sh/vuejs-ai/skills/vue-testing-best-practices) | 12.7K | Vitest、Vue Test Utils、异步响应时序与 Playwright；重点验证 C01 抽屉串任务 | 当前管理端尚未配置完整组件测试栈；安装技能不会自动增加这些依赖或完成浏览器验收 |
| [systematic-debugging / obra/superpowers](https://skills.sh/obra/superpowers/systematic-debugging) | 约 290K | 先复现、追数据路径、检验假设，再修复；适合本次审查问题逐项处理 | 和现有 TDD/代码审查/完成前验证配合，不另建重复执行体系 |
| [fastapi / fastapi/fastapi](https://skills.sh/fastapi/fastapi/fastapi) | 约 12K | 官方依赖注入、Pydantic、响应契约、同步/异步边界和 OpenAPI 维护 | 文档包含新版本功能，先核对 uv.lock；保留同步 SQLAlchemy 和 Nginx，不机械切换 SQLModel、异步 DB 或前端托管方式 |

对应的[本地审查报告](CODE_REVIEW_20261013.md)为带日期的未修问题基线，后续修复时重新核对。

优先补充身份授权、MySQL、Vue 测试和系统排错；Vue 规范与 FastAPI 官方技能作为日常实现资料。

## 安装记录与重建命令

已使用以下 Codex 安装器命令安装六项到 `C:/Users/LIU/.codex/skills/`，目录与 SKILL.md 均已核对。技能在下一轮可由目录发现；当前会话可显式读取需要的指引。以下命令用于其他环境重建，现有目录不要重复覆盖。

```powershell
# 从项目根目录执行；网络访问和用户技能目录写入需要运行环境允许。
$taskPython = '.\backend\.venv\Scripts\python.exe'
$taskSkillInstaller = 'C:\Users\LIU\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py'

& $taskPython $taskSkillInstaller --repo wshobson/agents --path plugins/developer-essentials/skills/auth-implementation-patterns --method git
& $taskPython $taskSkillInstaller --repo planetscale/database-skills --path skills/mysql --method git
& $taskPython $taskSkillInstaller --repo vuejs-ai/skills --path skills/vue-best-practices skills/vue-testing-best-practices --method git
& $taskPython $taskSkillInstaller --repo obra/superpowers --path skills/systematic-debugging --method git
& $taskPython $taskSkillInstaller --repo fastapi/fastapi --ref master --path fastapi/.agents/skills/fastapi --method git
```

当前已有 `test-driven-development`、`requesting-code-review`、`verification-before-completion` 和前端测试调试能力，可以继续使用，无需再装同名副本。

## 暂不作为默认推荐

- React/Next.js 和 Supabase/Postgres 技能与当前 Vue/MySQL 栈不同。
- `jeffallan/claude-skills@fastapi-expert` 内容强制 async I/O、禁止同步数据库，不适合直接套用当前同步 SQLAlchemy 服务；采用上表官方 FastAPI 技能，并按锁定版本筛选功能。
- 原生小程序检索有候选，但 `gourdbaby/wechat-miniprogram-skill` 来源规模小，部分规则过于绝对；Skyline 技能针对独立渲染体系，CloudBase 技能往往绑定云开发。当前不据此迁移平台或框架。
- 小程序当前优先解决接口 DTO、初核/终审枚举、文件访问、分页和补交，再维护实际 `.test.mjs` 与开发者工具验收；现有项目契约比通用模板更直接。

## 内容核对来源

- [身份授权原文](https://github.com/wshobson/agents/blob/main/plugins/developer-essentials/skills/auth-implementation-patterns/SKILL.md)
- [MySQL 原文](https://github.com/planetscale/database-skills/blob/main/skills/mysql/SKILL.md)
- [Vue 规范原文](https://github.com/vuejs-ai/skills/blob/main/skills/vue-best-practices/SKILL.md)、[Vue 测试原文](https://github.com/vuejs-ai/skills/blob/main/skills/vue-testing-best-practices/SKILL.md)
- [系统排错原文](https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md)
- [FastAPI 官方原文](https://github.com/fastapi/fastapi/blob/master/fastapi/.agents/skills/fastapi/SKILL.md)
