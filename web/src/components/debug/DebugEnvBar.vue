<script setup lang="ts">
import { computed } from 'vue'
import { useDebugContext } from '../../composables/useDebugContext'
import EnvPicker from './EnvPicker.vue'
import VariablesTable from './VariablesTable.vue'

const ctx = useDebugContext()
const initial = computed({
  get: () => ctx.initialVars.value,
  set: (v: Record<string, string>) => {
    if (ctx.environment.value) ctx.setInitialVars(ctx.environment.value.id, v)
  },
})
</script>

<template>
  <div class="env-switch">
    <span class="env-switch-label">调试环境</span>
    <EnvPicker seamless manage />
    <el-popover v-if="ctx.environment.value" placement="bottom-start" :width="860" trigger="click">
      <template #reference>
        <button type="button" class="env-switch-vars">
          变量<span class="env-switch-count">{{ ctx.varCount.value }}</span>
        </button>
      </template>
      <div class="env-switch-title">{{ ctx.environment.value.name }}</div>
      <VariablesTable v-model:initial="initial" :env-id="ctx.environment.value.id" confirm-delete />
    </el-popover>
  </div>
</template>

<style scoped>
.env-switch {
  display: inline-flex;
  align-items: stretch;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
  background: #fff;
  overflow: hidden;
}
.env-switch:focus-within {
  border-color: var(--el-color-primary);
}
.env-switch-label {
  display: flex;
  align-items: center;
  padding: 0 12px;
  border-right: 1px solid var(--el-border-color);
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 13px;
  white-space: nowrap;
}
.env-switch-vars {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border: none;
  border-left: 1px solid var(--el-border-color);
  background: #fff;
  color: var(--el-text-color-regular);
  font: inherit;
  font-size: 13px;
  white-space: nowrap;
  cursor: pointer;
}
.env-switch-vars:hover {
  background: var(--el-fill-color-light);
  color: var(--el-color-primary);
}
.env-switch-count {
  color: var(--ink-muted);
}
.env-switch-title {
  margin-bottom: 6px;
  font-weight: 600;
}
</style>
