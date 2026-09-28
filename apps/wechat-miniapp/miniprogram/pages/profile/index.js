import { getUserInfo, logout } from '../../api/user';
import { hasSession } from '../../utils/session';

const roleNames = {
  STUDENT: '学生',
  VOLUNTEER: '查课志愿者',
  STUDENT_AFFAIRS_MANAGER: '学生工作负责人',
  TEACHER_ADMIN: '教师管理员',
  SUPER_ADMIN: '超级管理员'
};

Page({
  data: {
    displayName: '',
    roleNames: []
  },

  onShow() {
    this.fetchUserInfo();
  },

  async fetchUserInfo() {
    this.setData({ displayName: '', roleNames: [] });
    if (!hasSession()) {
      wx.reLaunch({ url: '/pages/login/index' });
      return;
    }
    try {
      const user = await getUserInfo();
      if (user.binding_required) {
        wx.reLaunch({ url: '/pages/login/index' });
        return;
      }
      this.setData({
        displayName: user.display_name,
        roleNames: (user.roles || []).map(role => roleNames[role] || role)
      });
    } catch (err) {
      wx.showToast({ title: err.message || '身份信息加载失败', icon: 'none' });
    }
  },

  async handleLogout() {
    try {
      await logout();
    } finally {
      wx.removeStorageSync('currentAbnormal');
      wx.removeStorageSync('selectedAbnormal');
      wx.reLaunch({ url: '/pages/login/index' });
    }
  }
});
