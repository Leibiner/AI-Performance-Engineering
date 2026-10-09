<script setup lang="ts">
import { useDebugContext } from '../../composables/useDebugContext'
import EnvPicker from './EnvPicker.vue'
import VariablesTable from './VariablesTable.vue'

const ctx = useDebugContext()
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
    <el-popover v-if="ctx.environment.value" placement="bottom-end" :width="860" trigger="click">
      <template #reference>
        <el-button text bg size="small">
          变量<span class="debug-env-count">{{ ctx.varCount.value }}</span>
        </el-button>
      </template>
      <div class="debug-env-vars-title">{{ ctx.environment.value.name }}</div>
      <VariablesTable :env-id="ctx.environment.value.id" :initial="ctx.initialVars.value" />
    </el-popover>
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
.debug-env-count {
  margin-left: 6px;
  color: var(--ink-muted);
}
.debug-env-vars-title {
  margin-bottom: 6px;
  font-weight: 600;
}
</style>
