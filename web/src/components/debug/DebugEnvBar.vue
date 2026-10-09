<script setup lang="ts">
import EnvPicker from './EnvPicker.vue'

// 页头右侧的"调试环境"：只出现在会发请求的页面（接口、业务流程）。
// 接口页请求栏里的地址前缀、流程试跑对话框里的选择器，改的都是它这同一个值。
</script>

<template>
  <div class="debug-env-bar">
    <span
      class="debug-env-label"
      title="接口页的“发送”和业务流程的“试跑”都发往这里；发起运行时默认选中它，仍可在对话框里改。刷新后保留"
    >
      调试环境
    </span>
    <EnvPicker />
    <router-link class="debug-env-link" to="/environments">管理</router-link>
  </div>
</template>

<style scoped>
.debug-env-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.debug-env-label {
  color: var(--ink-muted);
  font-size: 13px;
  cursor: help;
}
.debug-env-link {
  color: var(--el-color-primary);
  font-size: 13px;
  text-decoration: none;
}
.debug-env-link:hover {
  text-decoration: underline;
}
</style>
