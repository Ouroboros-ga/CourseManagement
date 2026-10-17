# 学院工作区渲染守卫发布记录（2026-10-17）

仅管理端静态资源发布，不改后端、不跑迁移、不动生产开关。

## 版本

- 源码：`b13b4e3`（分支 `dev-main`，功能提交 `0da9e6f`）。
- 后端指针未变：`/opt/course-management/releases/20261017-coursetype-9cf47d5`。
- 管理端指针：`/opt/course-management/admin-web/current` → `releases/20261017-workspace-guard-b13b4e3`。
- 发布包：`/opt/course-management/incoming/web-b13b4e3.tar.gz`，SHA-256 `9df24827b08f647a61353faa8325bbba899aac351fcf71cb691d5cbbdb7ee877`，上传后在服务器 `sha256sum -c` 通过。
- 发布前指针：`releases/20261017-importhome-2e3e5cf`，目录完整保留。
- 版本目录内 `RELEASE_MANIFEST.json` 记录来源 SHA、前指针、包哈希和承接资源数。

## 变更内容

`apps/admin-web/src/components/workspace/CampusWorkspace.vue` 增加子组件渲染错误捕获，并把"学院上下文未就绪且在加载"从不可见的零高度 `v-loading` 改为骨架屏。模板改为互斥链：接口错误 → 渲染错误 → 骨架 → 空学院说明 → 插槽。

动机是"教务资料 → 作息与校历 / 发布给学生"整块空白且无任何提示。作息数据本身受生产开关限制（见[开关启用清单](../../../development/CAMPUS_SCOPED_FLAG_ROLLOUT_20261017.md)），本次不解决开关问题，只消除静默空白，使真实失败原因可见。

## 构建与验证

- `npm run build`（含 `vue-tsc`）通过。
- `node --test tests/*.test.mjs` 共 77 项全部通过，含本次新增 10 项。
- 新增的两项行为测试在旧组件版本上确认失败，属真回归测试：`tests/campus-workspace.test.mjs`（composable 状态收敛 5 项）、`tests/campus-workspace-render.test.mjs`（渲染状态与守卫契约 5 项）。
- 旧版本的 141 个 assets 文件承接进新版本目录，已打开页面的旧 chunk 引用不失效；线上核验 `assets/period-3-nDjkof.js` 仍返回 200。
- 切换后线上核验：`/dashboard/academic` 入口引用 `assets/index-8KCL6u9I.js`；新 chunk `assets/period-C_zEeWXU.js` 返回 200 且含守卫文案；`/health/ready` 为 `{"status":"ok","database":"up"}`。
- 未做：真实浏览器登录态下打开两个页签观察新提示条。守卫是否命中真实根因待线上使用者回报。

## 回退

原子切回前指针即可，不需要重启任何服务：

```bash
ln -sfn /opt/course-management/admin-web/releases/20261017-importhome-2e3e5cf \
  /opt/course-management/admin-web/current.pending
mv -T /opt/course-management/admin-web/current.pending /opt/course-management/admin-web/current
```

`index.html` 为 `no-store`，切换后刷新即生效。本次未触及数据库、迁移、权限和生产开关，回退不产生数据影响。
