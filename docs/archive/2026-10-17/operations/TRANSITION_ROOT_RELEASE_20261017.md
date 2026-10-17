# 页签过渡单根修复发布记录（2026-10-17）

仅管理端静态资源发布，不改后端、不跑迁移、不动生产开关。承接[渲染守卫发布](WORKSPACE_GUARD_RELEASE_20261017.md)。

## 根因

`<Transition mode="out-in">` 只能动画单个元素子节点。四个页签子组件是多根模板，Vue 把它们渲染成 fragment，因此从未挂载过渡钩子，离开动画的 `afterLeave` 永不触发，`isLeaving` 永久为真，Transition 此后只返回空占位注释节点。表现为"切走再切回，整块空白且无任何提示"。

命中位置：`ScopedAcademicBrowser`（7 根）、`CourseTypeManager`（3 根）、`OwnershipReconciliation`（6 根）、`ConfigurationImpacts`（7 根）。前两个正是最初上报的"教务资料 → 作息与校历 / 发布给学生"空白，第三个是"学校与学院管理 → 学院、教师与授权"空白。

## 版本

- 源码：`19438bb`（分支 `dev-main`）。
- 管理端指针：`/opt/course-management/admin-web/current` → `releases/20261017-transition-root-19438bb`。
- 发布前指针：`releases/20261017-workspace-guard-b13b4e3`，目录保留。
- 后端指针未变：`/opt/course-management/releases/20261017-coursetype-9cf47d5`。
- 发布包：`/opt/course-management/incoming/web-19438bb.tar.gz`，SHA-256 `2329fe959064fa0cae24685324e36a2c65249bc03b0666776e5e00c1e3148342`，服务器 `sha256sum -c` 通过。
- 承接上一版 175 个 assets，已打开页面的旧 chunk 引用不失效。

## 变更方式

在调用点包一层 `<div :key>`，与仓库里已有的 `administration`、`time`、`imports`、`groups` 分支写法一致，不改组件内部、不动样式。四个组件本身仍是多根，供非过渡场景使用。

## 验证

- 新增 `tests/transition-root-invariant.test.mjs`：遍历 `src` 下所有 `mode="out-in"` 的 Transition，解析子组件根节点链，多根即失败。在修复前确认报出上述 4 处，修复后归零。
- `node --test tests/*.test.mjs` 共 78 项全部通过；`npm run build`（含 `vue-tsc`）通过。
- 三个改动的视图 chunk 哈希变化且线上返回 200：`SchoolView-CZO8voiP.js`、`AcademicView-DS9nTaXW.js`、`InspectionsView-DTBrpw1x.js`。
- 线上入口 `assets/index-D0BqtFAG.js`；上一版 `index-8KCL6u9I.js` 与 `period-3-nDjkof.js` 仍 200；`/health/ready` 为 `database: up`。
- 拉取线上 `SchoolView-CZO8voiP.js` 核对：`ownership` 分支已编译为 `createElementBlock("div", …)` 包裹 `OwnershipReconciliation`。
- 未做：真实登录态下逐个页签往返点击。

## 回退

```bash
ln -sfn /opt/course-management/admin-web/releases/20261017-workspace-guard-b13b4e3 \
  /opt/course-management/admin-web/current.pending
mv -T /opt/course-management/admin-web/current.pending /opt/course-management/admin-web/current
```

`index.html` 为 `no-store`，切换后刷新即生效。未触及数据库、迁移、权限与生产开关。
