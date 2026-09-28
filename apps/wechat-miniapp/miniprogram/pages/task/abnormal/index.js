import { getTaskRoster } from '../../../api/task';
import Toast from 'tdesign-miniprogram/toast/index';

Page({
  data: {
    taskId: '',
    keyword: '',
    searchResults: [],
    roster: [],
    selectedList: [] // studentId is the internal ID; studentNo is displayed.
  },

  onLoad(options) {
    if (options.taskId) {
      this.setData({ taskId: options.taskId });
      this.loadRoster(options.taskId);
    }
    const current = wx.getStorageSync('currentAbnormal');
    if (current) {
      wx.removeStorageSync('currentAbnormal');
      if (current.taskId === options.taskId && Array.isArray(current.items)) {
        this.setData({ selectedList: current.items });
      }
    }
  },

  onKeywordChange(e) {
    this.setData({ keyword: e.detail.value });
  },

  async loadRoster(taskId) {
    try {
      wx.showLoading({ title: '加载名单中' });
      const response = await getTaskRoster(taskId);
      const roster = (response.items || []).map(student => ({
        studentId: student.student_id,
        studentNo: student.student_no,
        name: student.name
      }));
      this.setData({ roster });
    } catch (err) {
      Toast({ context: this, selector: '#t-toast', message: err.message || '名单加载失败' });
    } finally {
      wx.hideLoading();
    }
  },

  async handleSearch() {
    const keyword = this.data.keyword.trim().toLowerCase();
    if (!keyword) {
      Toast({ context: this, selector: '#t-toast', message: '请输入搜索词' });
      return;
    }
    const results = this.data.roster.filter(student =>
      student.name.toLowerCase().includes(keyword) || student.studentNo.toLowerCase().includes(keyword));
    this.setData({ searchResults: results });
  },

  addStudent(e) {
    const student = e.currentTarget.dataset.item;
    const selectedList = [...this.data.selectedList];

    // 判断是否已存在
    const exists = selectedList.some(s => s.studentId === student.studentId);
    if (exists) {
      Toast({ context: this, selector: '#t-toast', message: '该学生已在列表中' });
      return;
    }

    selectedList.push({
      ...student,
      type: 'ABSENT',
      typeName: '旷课'
    });

    this.setData({
      selectedList,
      keyword: '',
      searchResults: []
    });
  },

  removeStudent(e) {
    const { index } = e.currentTarget.dataset;
    const selectedList = [...this.data.selectedList];
    selectedList.splice(index, 1);
    this.setData({ selectedList });
  },

  onTypeChange(e) {
    const { index } = e.currentTarget.dataset;
    const { value } = e.detail;
    const selectedList = [...this.data.selectedList];
    selectedList[index].type = value;
    selectedList[index].typeName = { LATE: '迟到', ABSENT: '旷课', LEAVE: '请假' }[value];
    this.setData({ selectedList });
  },

  handleConfirm() {
    const { selectedList } = this.data;
    wx.setStorageSync('selectedAbnormal', {
      taskId: this.data.taskId,
      items: selectedList
    });
    wx.navigateBack();
  }
});
