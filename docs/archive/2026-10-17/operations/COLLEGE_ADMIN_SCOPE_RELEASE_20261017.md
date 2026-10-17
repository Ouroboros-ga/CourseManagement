# 学院管理与作息入口作用域拆分发布记录（2026-10-17）

仅管理端静态资源发布，不改后端、不跑迁移、不动生产开关。承接[页签过渡单根修复](TRANSITION_ROOT_RELEASE_20261017.md)。

## 发布内容

源码 `3d097bd`（分支 `dev-main`）。构建时 HEAD 为 `14002e4`，该提交只改 `backend/app/modules/academic/roster_index.py`，`git diff --name-only 3d097bd HEAD -- apps/admin-web` 为空，`git status --short apps/admin-web` 为空，因此产物即 `3d097bd` 的 Web 内容。

- 学校与学院管理：`SchoolTimeTemplates` 与"当前学院：改名/停用"从 `CampusAdministration` 移除；"管理对象"提升为页面级上下文条，选择器、状态标签、重命名、停用/恢复集中在此，全页只剩一个学院选择器。
- 学期与平台设置：新增"学校作息模板"页签，仅 `SUPER_ADMIN` 且 `campusRuntime.scheduling` 为真时出现；学校主体 ID 改由 `watch(canEditSchoolTemplates, …, { immediate: true })` 取得，不再假设它早于本页挂载就绪。
- 教务资料：本院作息页签改由 `business_scoped && scheduling` 决定出现，页签名改为"本院作息与校历"，删除只能读提示的降级条。
- 教师固定学院归属不再显示裸 `college_id`，`handoff` 不再渲染为 `[object Object]`，已绑定时按钮禁用并提示当前归属。
- 跨范围授权的范围约束由段落改为随"资源范围"选择实时变化的字段提示。
- 删除无任何路由引用的 `components/campus/CampusConfiguration.vue`。

生产开关现状（configuration/academic_scoped/publication=true，business_scoped/scheduling=false）下，作息入口收敛为一个：学期与平台设置 → 节次作息时间表。

## 版本与指针

- 管理端指针：`/opt/course-management/admin-web/current` → `releases/20261017-college-admin-scope-3d097bd`。
- 发布前指针：`releases/20261017-transition-root-19438bb`，目录保留。
- 后端指针未变：`/opt/course-management/releases/20261017-coursetype-9cf47d5`。
- 发布包：`/opt/course-management/incoming/web-3d097bd.tar.gz`，SHA-256 `1d73fbe3f4a12d07150f7e01db22b2c421c1c4a7893d0749b1d4171ee74b11db`，服务器 `sha256sum -c` 通过。
- 沿用"上一版 assets 全量承接 + 本版覆盖"的做法：`cp -a` 上一版内容后解包新版，目录 270 个 assets（上一版 233）。已打开页面的旧 chunk 引用不失效。

## 验证

- `npm run build`（含 `vue-tsc`）通过；`node --test tests/*.test.mjs` 共 83 项通过，含新增 `tests/college-admin-scope.test.mjs` 5 项作用域守卫与既有的 out-in 过渡单根守卫。
- 切换指针前在待发布目录内核对编译产物：`SchoolView-BDLvo3lC.js` 含"管理对象/重命名/停用管理对象/恢复管理对象"且不含"学校作息模板"；`SettingsView-AbXTHWZv.js` 含"学校作息模板"；`AcademicView-B63FqqNK.js` 含"本院作息与校历"且不含"学院作息业务尚未启用"；无 `CampusConfiguration` chunk。
- 线上：`index.html` 200 且 `Cache-Control: no-store`，入口为 `assets/index-CPA0y1LA.js`；`SchoolView-BDLvo3lC.js`、`SettingsView-AbXTHWZv.js`、`AcademicView-B63FqqNK.js` 均 200；上一版 `SchoolView-CZO8voiP.js`、`index-D0BqtFAG.js` 仍 200；`/health/ready` 200。`nginx -t` 通过，未 reload（root 路径未变）。
- 未做：真实登录态下逐个页签往返点击。上下文条、授权字段提示和教师归属提示的实际渲染需使用者硬刷新后确认。

## 回退

```bash
ln -sfn /opt/course-management/admin-web/releases/20261017-transition-root-19438bb \
  /opt/course-management/admin-web/current.pending
mv -T /opt/course-management/admin-web/current.pending /opt/course-management/admin-web/current
```

`index.html` 为 `no-store`，切换后刷新即生效。未触及数据库、迁移、权限与生产开关。

## 未随本次处理

全校节次作息与校历写入在生产上只对 `SUPER_ADMIN` 开放，教师管理员点保存会得到指向不存在入口的 403。核实过程与三个待定口径见[开关联动清单 §9.1](../../../development/CAMPUS_SCOPED_FLAG_ROLLOUT_20261017.md)。用户已明确"先不动，以后再说"。
