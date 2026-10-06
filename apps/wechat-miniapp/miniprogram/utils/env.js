// 开发者工具使用本机 API；真机须改为已配置合法域名的 HTTPS 服务。
const LOCAL_BASE_URL = 'https://course.zsitai.xyz';

export function getBaseURL() {
  const external = typeof wx !== 'undefined' && typeof wx.getExtConfigSync === 'function'
    ? wx.getExtConfigSync() : {};
  const configured = external?.apiBaseUrl || LOCAL_BASE_URL;
  if (!/^https?:\/\/[^/]+/i.test(configured)) {
    throw new Error('apiBaseUrl 必须为 HTTP(S) 地址');
  }
  return configured.replace(/\/+$/, '');
}
