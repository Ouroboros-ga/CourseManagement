<script setup lang="ts">
import { useSessionStore } from '../../stores/session'
const session = useSessionStore()
const scoped = (path: string, tab?: string) => ({ path, query: {
  workspace_id: session.workspaceCollegeId, semester_id: session.currentSemesterId,
  ...(tab ? { tab } : {})
} })
</script>

<template>
  <details class="conflict-help">
    <summary>重名、编号不符或缺少档案，怎么处理？</summary>
    <p>学生按学号、教师按工号关联。姓名相同不会合并，不能默认选择本学院的同名教师。</p>
    <ol>
      <li>先在“查看问题与内容”核对文件、行号、工号／学号与姓名。</li>
      <li>缺档案：先保存本次教师／学生名单；编号或姓名填错：核对原始资料并修正表格。</li>
      <li>同名教师：补充准确工号；负责人换人或任期重叠：到班级负责人页面执行交接。</li>
      <li>返回这里添加修正后的文件，再读取预览。已经保存的其他资料无需重导。</li>
    </ol>
    <p>课表中的授课姓名待关联可以保留，但不会产生教师权限。责任关系人员不明确时不能保存；已保存的课表也可通过任课教师页面补关联。</p>
    <div class="help-links">
      <router-link v-if="session.hasPermission('staff.manage')" target="_blank" :to="scoped('/dashboard/staff')">核对教职工档案 ↗</router-link>
      <router-link v-if="session.hasPermission('student.read')" target="_blank" :to="scoped('/dashboard/students', 'directory')">核对学生与行政班 ↗</router-link>
      <router-link v-if="session.hasPermission('staff.manage')" target="_blank" :to="scoped('/dashboard/students', 'responsibilities')">维护责任关系与交接 ↗</router-link>
      <router-link v-if="session.hasPermission('staff.manage')" target="_blank" :to="scoped('/dashboard/academic', 'teaching-assignments')">补充授课关联 ↗</router-link>
    </div>
    <p class="hint">处理入口在新标签页打开。回到这里后须重新读取预览，旧核对结果不会自动继续生效。</p>
  </details>
</template>

<style scoped>
.conflict-help { margin:18px 0;padding:16px;border:1px solid var(--line);font-size:13px;line-height:1.8; }.conflict-help summary { cursor:pointer;font-weight:600; }.conflict-help ol { padding-left:22px; }.help-links { display:flex;gap:16px;flex-wrap:wrap;margin-top:10px; }.hint { color:var(--ink-mute); }
</style>
