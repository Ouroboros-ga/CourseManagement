import { logout } from '../../api/user';

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
  }
});
