import { searchStudents } from '../../../api/task';
import Toast from 'tdesign-miniprogram/toast/index';

Page({
  data: {
    taskId: '',
    keyword: '',
    allStudents: [],
    searchResults: [],
    selectedList: [] // { studentId, name, type }
  },

  onLoad(options) {
    if (options.taskId) {
      this.setData({ taskId: options.taskId });
      this.fetchAllStudents();
    }
    const current = wx.getStorageSync('currentAbnormal');
    if (current && Array.isArray(current)) {
      this.setData({ selectedList: current });
      wx.removeStorageSync('currentAbnormal');
    }
  },
  
  async fetchAllStudents() {
    try {
      wx.showLoading({ title: '加载名单...' });
      const res = await searchStudents(this.data.taskId, '');
      const results = (res?.items || res || []).map(item => ({
        ...item,
        studentId: item.student_id || item.studentId,
        studentNo: item.student_no || item.studentNo,
        name: item.name
      }));
      this.setData({ allStudents: results, searchResults: results });
    } catch (err) {
      Toast({ context: this, selector: '#t-toast', message: '加载名单失败' });
    } finally {
      wx.hideLoading();
    }
  },

  onKeywordChange(e) {
    const keyword = e.detail.value || '';
    this.setData({ keyword });
    this.filterStudents(keyword);
  },
  
  filterStudents(keyword) {
    if (!keyword.trim()) {
      this.setData({ searchResults: this.data.allStudents });
      return;
    }
    const lowerKey = keyword.trim().toLowerCase();
    const filtered = this.data.allStudents.filter(s => 
      (s.name && s.name.toLowerCase().includes(lowerKey)) || 
      (s.studentNo && s.studentNo.toLowerCase().includes(lowerKey))
    );
    this.setData({ searchResults: filtered });
  },

  handleSearch() {
    this.filterStudents(this.data.keyword);
  },

  addStudent(e) {
    const student = e.currentTarget.dataset.item;
    const { selectedList } = this.data;
    
    // 判断是否已存在
    const exists = selectedList.some(s => s.studentId === student.studentId);
    if (exists) {
      Toast({ context: this, selector: '#t-toast', message: '该学生已在列表中' });
      return;
    }

    selectedList.push({
      ...student,
      type: '旷课' // 默认类型
    });

    this.setData({ 
      selectedList,
      keyword: '',
      searchResults: [] 
    });
  },

  removeStudent(e) {
    const { index } = e.currentTarget.dataset;
    const { selectedList } = this.data;
    selectedList.splice(index, 1);
    this.setData({ selectedList });
  },

  onTypeChange(e) {
    const { index } = e.currentTarget.dataset;
    const { value } = e.detail;
    const { selectedList } = this.data;
    selectedList[index].type = value;
    this.setData({ selectedList });
  },

  handleConfirm() {
    const { selectedList } = this.data;
    wx.setStorageSync('selectedAbnormal', selectedList);
    wx.navigateBack();
  }
});
