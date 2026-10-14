import { getUserInfo } from '../../api/user';
import { request } from '../../utils/request';

const roleMap = {
  'STUDENT': '普通学生',
  'VOLUNTEER': '查课志愿者',
  'STUDENT_AFFAIRS_MANAGER': '学生负责人',
  'ADMIN': '教师管理员',
  'TEACHER_ADMIN': '教师管理员',
  'SUPER_ADMIN': '超级管理员'
};

Page({
  data: {
    userInfo: {},
    roleName: '',
    isVolunteer: false,
    isAdmin: false
  },

  onShow() {
    this.fetchUserInfo();
  },

  async fetchUserInfo() {
    try {
      const token = wx.getStorageSync('token');
      if (!token) {
        // 未登录则跳转到登录页
        wx.reLaunch({ url: '/pages/login/index' });
        return;
      }
      const data = await getUserInfo();

      let role = 'STUDENT';
      if (data.roles && Array.isArray(data.roles)) {
        if (data.roles.includes('SUPER_ADMIN')) role = 'SUPER_ADMIN';
        else if (data.roles.includes('TEACHER_ADMIN') || data.roles.includes('ADMIN')) role = 'ADMIN';
        else if (data.roles.includes('STUDENT_AFFAIRS_MANAGER')) role = 'STUDENT_AFFAIRS_MANAGER';
        else if (data.roles.includes('VOLUNTEER')) role = 'VOLUNTEER';
      } else if (data.role) {
        role = data.role;
      }

      let name = data.display_name || data.name || '';
      let surname = name ? name.charAt(0) : '';

      let greetingText = '你好，同学';
      if (role === 'TEACHER_ADMIN' || role === 'SUPER_ADMIN' || role === 'ADMIN') {
        greetingText = `您好，${surname ? surname + '老师' : '老师'}`;
      } else {
        greetingText = `你好，${surname ? surname + '同学' : '同学'}`;
      }

      // 基于权限（或角色）计算菜单显示
      const perms = data.permissions || [];
      const hasPerm = (p) => perms.includes(p);

      // 只要有查课读取权限或者是相关角色，就展示查课任务
      const isVolunteer = hasPerm('inspection.read') || role === 'VOLUNTEER' || role === 'STUDENT_AFFAIRS_MANAGER' || role === 'SUPER_ADMIN';

      // 只要有初审/终审权限或者是相关角色，就展示管理专区
      const isAdmin = hasPerm('objection.initial_review') || hasPerm('objection.final_review') || ['ADMIN', 'TEACHER_ADMIN', 'SUPER_ADMIN', 'STUDENT_AFFAIRS_MANAGER'].includes(role);

      this.setData({
        userInfo: data,
        roleName: roleMap[role] || role,
        isVolunteer,
        isAdmin,
        greetingText
      });
    } catch (err) {
      console.error('Failed to fetch user info', err);
    }
  },

  goToTaskList() {
    wx.navigateTo({ url: '/pages/task/list/index' });
  },

  goToAdminPanel() {
    wx.navigateTo({ url: '/pages/admin/index' });
  },

  goToRecordList() {
    wx.navigateTo({ url: '/pages/record/list/index' });
  }
});
