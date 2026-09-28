import { getUserInfo } from '../../api/user';
import { hasSession } from '../../utils/session';

const roleMap = {
  'STUDENT': '学生',
  'VOLUNTEER': '查课志愿者',
  'STUDENT_AFFAIRS_MANAGER': '学生工作负责人',
  'TEACHER_ADMIN': '教师管理员',
  'SUPER_ADMIN': '超级管理员'
};

Page({
  data: {
    userInfo: {},
    roleName: '',
    isVolunteer: false
  },

  onShow() {
    this.fetchUserInfo();
  },

  async fetchUserInfo() {
    try {
      if (!hasSession()) {
        wx.reLaunch({ url: '/pages/login/index' });
        return;
      }
      const data = await getUserInfo();
      if (data.binding_required) {
        wx.reLaunch({ url: '/pages/login/index' });
        return;
      }
      const roles = data.roles || [];
      const displayRole = ['VOLUNTEER', 'STUDENT_AFFAIRS_MANAGER', 'TEACHER_ADMIN', 'SUPER_ADMIN', 'STUDENT']
        .find(role => roles.includes(role));
      this.setData({
        userInfo: data,
        roleName: roleMap[displayRole] || '',
        isVolunteer: roles.includes('VOLUNTEER')
      });
    } catch (err) {
      console.error('Failed to fetch user info', err);
    }
  },

  goToTaskList() {
    wx.navigateTo({ url: '/pages/task/list/index' });
  }
});
