import { logout, unbindStudent } from '../../api/user';
import Dialog from 'tdesign-miniprogram/dialog/index';
import Toast from 'tdesign-miniprogram/toast/index';

Page({
  async handleLogout() {
    try {
      await logout();
    } catch (err) {
      console.warn('Logout api failed', err);
    } finally {
      wx.removeStorageSync('token');
      wx.reLaunch({
        url: '/pages/login/index'
      });
    }
  },

  handleRebind() {
    Dialog.confirm({
      title: '确认重新绑定',
      content: '重新绑定将解除当前微信与该学号的关联，您需要重新登录并绑定新的账号。',
      confirmBtn: '确定换绑',
      cancelBtn: '取消',
    }).then(async () => {
      try {
        await unbindStudent();
        wx.removeStorageSync('token');
        Toast({
          context: this,
          selector: '#t-toast',
          message: '解绑成功',
          theme: 'success',
          direction: 'column',
        });
        setTimeout(() => {
          wx.reLaunch({
            url: '/pages/login/index?rebind=true'
          });
        }, 1000);
      } catch (err) {
        Toast({
          context: this,
          selector: '#t-toast',
          message: err.message || '解绑失败',
          theme: 'error',
          direction: 'column',
        });
      }
    }).catch(() => {
      // 取消操作
    });
  }
});
