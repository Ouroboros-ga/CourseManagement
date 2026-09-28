import { bindStudent, getUserInfo, login } from '../../api/user';
import { hasSession } from '../../utils/session';
import Message from 'tdesign-miniprogram/message/index';

function wxLoginCode() {
  return new Promise((resolve, reject) => {
    wx.login({
      success: (result) => result.code ? resolve(result.code) : reject(new Error('微信登录未返回 code')),
      fail: reject,
    });
  });
}

Page({
  data: {
    needBinding: false,
    studentNo: '',
    bindingCode: '',
    busy: false,
  },

  async onLoad() {
    if (!hasSession()) return;
    try {
      const me = await getUserInfo();
      if (me.binding_required) this.setData({ needBinding: true });
      else wx.switchTab({ url: '/pages/index/index' });
    } catch {
      // 旧会话失效时保留登录入口，用户可重新发起微信登录。
    }
  },

  onStudentNoChange(event) {
    this.setData({ studentNo: event.detail.value });
  },

  onBindingCodeChange(event) {
    this.setData({ bindingCode: event.detail.value });
  },

  async handleWechatLogin() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      const code = await wxLoginCode();
      const auth = await login({ code });
      const me = await getUserInfo();
      if (auth.need_binding || me.binding_required) {
        this.setData({ needBinding: true });
      } else {
        wx.switchTab({ url: '/pages/index/index' });
      }
    } catch (error) {
      Message.error({ context: this, content: error.message || '登录失败，请重试' });
    } finally {
      this.setData({ busy: false });
    }
  },

  async handleBind() {
    const studentNo = this.data.studentNo.trim();
    const bindingCode = this.data.bindingCode.trim();
    if (!studentNo || !bindingCode) {
      Message.warning({ context: this, content: '请输入学号和一次性绑定码' });
      return;
    }
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      await bindStudent({ student_no: studentNo, binding_code: bindingCode });
      this.setData({ bindingCode: '' });
      wx.switchTab({ url: '/pages/index/index' });
    } catch (error) {
      Message.error({ context: this, content: error.message || '绑定失败，请重试' });
    } finally {
      this.setData({ busy: false });
    }
  },
});
