import { searchStudents } from '../../../api/task';
import Toast from 'tdesign-miniprogram/toast/index';

Page({
  data: {
    taskId: '',
    keyword: '',
    allStudents: [],
    selectedList: [],
    displayList: []
  },

  onLoad(options) {
    if (options.taskId) {
      this.setData({ taskId: options.taskId });
    }
    const current = wx.getStorageSync('currentAbnormal');
    if (current && Array.isArray(current)) {
      this.setData({ selectedList: current });
      wx.removeStorageSync('currentAbnormal');
    }
    if (this.data.taskId) {
      this.fetchAllStudents();
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
      this.setData({ allStudents: results });
      this.updateDisplayList();
    } catch (err) {
      Toast({ context: this, selector: '#t-toast', message: '加载名单失败' });
    } finally {
      wx.hideLoading();
    }
  },

  updateDisplayList() {
    const { keyword, allStudents, selectedList } = this.data;
    
    let unselectedFiltered = allStudents.filter(s => !selectedList.some(sel => sel.studentId === s.studentId));
    if (keyword.trim()) {
      const lowerKey = keyword.trim().toLowerCase();
      unselectedFiltered = unselectedFiltered.filter(s => 
        (s.name && s.name.toLowerCase().includes(lowerKey)) || 
        (s.studentNo && s.studentNo.toLowerCase().includes(lowerKey))
      );
    }
    
    const displayList = [
      ...selectedList.map(s => ({ ...s, _selected: true })),
      ...unselectedFiltered.map(s => ({ ...s, _selected: false }))
    ];
    
    this.setData({ displayList });
  },

  onKeywordChange(e) {
    this.setData({ keyword: e.detail.value || '' });
    this.updateDisplayList();
  },

  handleSearch() {
    this.updateDisplayList();
  },

  toggleStudent(e) {
    const student = e.currentTarget.dataset.item;
    const { selectedList } = this.data;
    
    const index = selectedList.findIndex(s => s.studentId === student.studentId);
    if (index > -1) {
      // 移除
      selectedList.splice(index, 1);
    } else {
      // 添加到最前，保证置顶效果
      selectedList.unshift({
        ...student,
        type: '旷课'
      });
    }
    
    this.setData({ selectedList });
    this.updateDisplayList();
  },

  onTypeChange(e) {
    const { studentid } = e.currentTarget.dataset;
    const { value } = e.detail;
    const { selectedList } = this.data;
    
    const student = selectedList.find(s => s.studentId === studentid);
    if (student) {
      student.type = value;
      this.setData({ selectedList });
      this.updateDisplayList();
    }
  },

  handleConfirm() {
    const { selectedList } = this.data;
    wx.setStorageSync('selectedAbnormal', selectedList);
    wx.navigateBack();
  }
});
