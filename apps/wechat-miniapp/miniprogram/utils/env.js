// 当前环境配置
//
// 只把生产地址写进源码。开发/联调地址不再硬编码：小程序包可被反编译
// （wxapkg → js），内网 IP 与调试端口一旦打进发布包，等于公开内网拓扑，
// 属于持续性信息泄漏（CWE-200），靠"发布前记得改回来"无法根治。
//
// 需要连本地或内网后端时，在开发者工具控制台执行一次：
//   wx.setStorageSync('debugBaseURL', 'http://<你的内网地址>:18080')
// 恢复生产：wx.removeStorageSync('debugBaseURL')
// 该值只存在于本机 Storage，不进入代码包、不随版本发布。

const PROD_BASE_URL = 'https://course.zsitai.xyz';

function readDebugBaseURL() {
  try {
    const value = wx.getStorageSync('debugBaseURL');
    return typeof value === 'string' ? value.trim() : '';
  } catch (e) {
    // 非小程序运行时（单元测试 / node）没有 wx，按生产地址处理。
    return '';
  }
}

const debugBaseURL = readDebugBaseURL();

export const env = debugBaseURL ? 'dev' : 'prod'; // 'dev' | 'prod'

export const config = {
  dev: {
    baseURL: debugBaseURL || PROD_BASE_URL
  },
  prod: {
    baseURL: PROD_BASE_URL
  }
};

export const getBaseURL = () => config[env].baseURL;
