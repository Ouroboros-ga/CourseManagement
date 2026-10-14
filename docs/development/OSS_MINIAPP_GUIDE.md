# 小程序文件接入说明（2026-10-13）

## 当前方案与已知信息

| 项目 | 内容 |
| --- | --- |
| Bucket | `oss-pai-um7e66idcat8ihfw7v-cn-shanghai` |
| 地域 | 华东 2（上海），`cn-shanghai` |
| 外网 Endpoint | `https://oss-cn-shanghai.aliyuncs.com` |
| 服务器 | 阿里云 ECS；ECS 所在地域尚未确认 |
| ECS 角色 | 用户配置的 `tmp.course`；实际绑定和云端权限尚未验收 |
| 存储权限 | 私有桶；RAM 角色限定本桶 GetObject / PutObject / DeleteObject |
| 客户端接入 | 通过现有后端上传与短期下载，不直传 OSS |
| 当前交付状态 | 本地代码接入；尚未部署、迁移或进行微信真机/真实 OSS 验收 |

Bucket 与 Endpoint 供理解部署用途，不填入小程序上传地址。小程序不安装 OSS SDK，不接收 AccessKey、AppSecret、STS 凭据、object_key。服务器利用 ECS RAM 角色自动刷新临时凭据。

## 上传

`POST /api/v1/files`，登录且绑定完成，multipart 字段 `file`、`category`。业务域名从现有 `getBaseURL()` 获取；当前项目 prod 配置是 `https://course.zsitai.xyz`，上线时仍须核对目标。

```javascript
// 示意代码：纳入现有上传封装，失败时保留用户选中的本地图片。
function uploadMaterial(filePath, category) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${getBaseURL()}/api/v1/files`,
      filePath,
      name: 'file',
      formData: { category },
      header: { Authorization: `Bearer ${wx.getStorageSync('token')}` },
      success(res) {
        try {
          const payload = JSON.parse(res.data);
          if (res.statusCode >= 200 && res.statusCode < 300) resolve(payload.data);
          else reject({ status: res.statusCode, ...payload });
        } catch (_) { reject(new Error('上传响应无法解析')); }
      },
      fail: reject
    });
  });
}
```

- 查课照片：`SUBMISSION_PHOTO`；学生异议证明：`OBJECTION_PROOF`。`TEMP` 为通用临时材料，不能替代上述业务类别。
- 默认图片格式 jpg/jpeg/png/webp，单文件最大 10 MiB，最多 4000 万像素；内容签名、尺寸和格式由后端验证，实际部署配置可调整。
- 上传返回 `data.id`（字符串）、`status=READY`、格式、大小等。提交查课/异议时只传对应 `file_ids: [id]`；不得转成 Number/parseInt 或提交 URL、路径。
- 上传接口与业务提交是两次操作，上传成功不等于业务提交成功；业务提交失败保留已上传的 file_id，避免重复上传。
- 401 上传失败：复用 `utils/request.js` 的串行 `refreshSession()`，成功后用同一个 filePath 至多重试一次；该函数当前为模块私有，开发者需将其导出或在同模块提供上传封装，不另写第二套刷新逻辑。普通 JSON request 的自动刷新不会自动覆盖 wx.uploadFile。不要覆盖 multipart Content-Type。
- 默认每次查课提交最多 5 张；异议最多 5 张，以上为部署可调整参数。

## 查看证明与照片

1. 带登录认证请求 `GET /api/v1/files/{file_id}/access`。
2. 取成功信封的 `data.url`、`expires_in`、`expires_at`；默认有效期 300 秒。
3. 若 url 为 `/api/...` 相对路径，用业务 API 的 origin 拼成绝对 HTTPS 地址，再交给 `wx.previewImage` 或 `wx.downloadFile`。保留完整查询参数，不重编码整条 URL。
4. 重新打开、失效或切换账号时重新申请访问链接。只在页面内存短期缓存，按账号隔离，退出清空；不写永久存储，不记录完整签名 URL。

```javascript
const access = await request({ url: `/api/v1/files/${fileId}/access` });
const url = access.url.startsWith('/')
  ? `${getBaseURL().replace(/\/$/, '')}${access.url}`
  : access.url;
wx.previewImage({ current: url, urls: [url] });
```

后端先核对文件所属业务与用户权限再发签名。下载请求只校验签名、有效期和文件状态；短期链接在有效期内是可转交使用的访问凭证，权限撤销不会即时撤销已发出的签名。签名到期返回 403；文件已清理/保留期结束返回 410；无权申请或文件不存在返回 404；OSS 访问故障返回 503 `UPSTREAM_UNAVAILABLE`。403 仅重新申请一次，410 不无限重试。

## 微信域名与删除

本次采用后端代理：request、uploadFile、downloadFile 合法域名配置业务 HTTPS 域名即可，不要求配置 OSS 桶域名，不要求桶开放公共读取或 OSS CORS。微信平台域名审核与真机测试仍需开发者验证。若以后改成 OSS 直传/直读，必须另行设计受限凭据、上传完成核验及域名配置。

当前没有供普通客户端直接删除 OSS 文件的公开接口。用户修改材料只调整业务引用；后端按保留策略清理。不得自行调用 DeleteObject，也不要设置会绕过“未完成异议暂停清理”的桶生命周期自动删除。

## 开发者验收

测试账号验证：上传图片 → 返回字符串 file_id → 正式提交关联 → 本人/授权审核人可预览 → 无权限账号申请返回 404 → 伪造/过期签名返回 403 → 401 上传仅重试一次 → 切换账号无旧链接残留。模拟 wx 和本地测试不能代替微信编译、HTTPS 合法域名及真机验收。
