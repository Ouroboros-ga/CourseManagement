import { login, bindStudent, logout } from '../../api/user';
import Toast from 'tdesign-miniprogram/toast/index';
import Message from 'tdesign-miniprogram/message/index';

Page({
  data: {
    needBinding: false,
    name: '',
    studentId: ''
  },

  onLoad(options) {
    if (options.rebind === 'true') {
      // 携带 rebind 参数进入时，自动触发微信登录，以获取需要绑定的状态
      this.handleLogin();
    }
  },

  onNameChange(e) {
    this.setData({ name: e.detail.value });
  },

  onStudentIdChange(e) {
    this.setData({ studentId: e.detail.value });
  },

  async handleLogin() {
    try {
      wx.showLoading({ title: '登录中...' });
      const loginRes = await wx.login();
      if (!loginRes.code) {
        throw new Error('微信登录失败');
      }

      const authData = await login({ code: loginRes.code });
      const token = authData?.token || authData?.access_token;
      if (token) {
         wx.setStorageSync('token', token);
      }

      wx.hideLoading();

      // 如果后端明确返回无需绑定，或者不是新号，直接进首页
      if (authData?.need_binding === false) {
        Toast({ context: this, selector: '#t-toast', message: '登录成功', theme: 'success' });
        setTimeout(() => {
          wx.switchTab({ url: '/pages/index/index' });
        }, 1000);
      } else {
        // 否则显示绑定表单
        this.setData({ needBinding: true });
        Message.info({
          context: this,
          offset: [20, 32],
          duration: 3000,
          content: '请先绑定学号',
        });
      }
    } catch (err) {
      wx.hideLoading();
      Message.error({
        context: this,
        offset: [20, 32],
        duration: 3000,
        content: err.msg || err.message || err.detail || '登录失败，请重试',
      });
    }
  },

  async handleBind() {
    const { name, studentId } = this.data;
    if (!name || !studentId) {
      Message.warning({
        context: this,
        offset: [20, 32],
        duration: 3000,
        content: '请完整填写绑定码和学号',
      });
      return;
    }

    try {
      wx.showLoading({ title: '绑定中...' });
      
      await bindStudent({ name, studentId });
      
      wx.hideLoading();
      Toast({
        context: this,
        selector: '#t-toast',
        message: '绑定成功',
        theme: 'success', 
      });

      setTimeout(() => {
        wx.switchTab({
          url: '/pages/index/index',
        });
      }, 1000);
    } catch (err) {
      wx.hideLoading();
      Message.error({
        context: this,
        offset: [20, 32],
        duration: 3000,
        content: err.msg || err.message || err.detail || '绑定失败，请重试',
      });
    }
  },

  async cancelBindAndLogout() {
    try {
      wx.showLoading({ title: '取消中...' });
      await logout();
    } catch (e) {
      // 忽略
    } finally {
      wx.removeStorageSync('token');
      this.setData({ needBinding: false });
      wx.hideLoading();
    }
  }
});
