<script setup lang="ts">
import CampusWorkspace from '../components/workspace/CampusWorkspace.vue'
import StaffDirectory from '../components/staff/StaffDirectory.vue'
</script>
<template>
  <section>
    <header class="page-head"><h1>教职工档案</h1><p class="sub">维护本院教职工档案、登录账号关联与绑定码；档案只代表归属，不授予任何管理权限。</p></header>
    <div class="tab-stage">
      <CampusWorkspace v-slot="scope"><StaffDirectory :college-id="scope.collegeId" /></CampusWorkspace>
    </div>
  </section>
</template>
