// 当前环境配置
export const env = 'prod'; // 'dev' | 'prod'

export const config = {
  dev: {
    baseURL: 'http://10.253.168.127:18080'
  },
  prod: {
    baseURL: 'https://course.zsitai.xyz'
  }
};

export const getBaseURL = () => config[env].baseURL;
