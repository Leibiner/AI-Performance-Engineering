<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useDebugContext } from '../../composables/useDebugContext'
import EnvTypeTag from '../EnvTypeTag.vue'

withDefaults(defineProps<{ seamless?: boolean }>(), { seamless: false })

const { envId, environments, environment, loadEnvironments } = useDebugContext()
// 每次挂载都重新拉一次：从被测环境页改完回来，列表就是新的
onMounted(() => {
  void loadEnvironments()
})
function onVisibleChange(open: boolean): void {
  if (open) void loadEnvironments()
}

// 按地址长度给宽度，长地址不至于被截断，短地址不占位
const width = computed(() => {
  const url = environment.value?.baseUrl ?? '选择被测环境'
  return `${Math.min(460, Math.max(200, Math.round(url.length * 7.4) + 96))}px`
})
</script>

<template>
  <el-select
    v-model="envId"
    class="env-picker"
    :class="{ 'is-seamless': seamless }"
    :style="{ width }"
    placeholder="选择调试环境"
    :title="environment ? `当前调试环境「${environment.name}」：所有接口的发送和业务流程的试跑都发往这里` : '先选择调试环境'"
    no-data-text="还没有被测环境，先到“被测环境”页面新建"
    @visible-change="onVisibleChange"
  >
    <template #label>
      <span v-if="environment" class="env-picker-label">
        <EnvTypeTag :type="environment.type" />
        <span class="env-picker-url">{{ environment.baseUrl }}</span>
      </span>
    </template>
    <el-option v-for="e in environments" :key="e.id" :label="e.name" :value="e.id">
      <span class="env-option">
        <EnvTypeTag :type="e.type" />
        <span class="env-option-name">{{ e.name }}</span>
        <span class="env-option-url">{{ e.baseUrl }}</span>
      </span>
    </el-option>
  </el-select>
</template>

<style scoped>
.env-picker-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
}
.env-picker-url {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
}
.env-picker.is-seamless :deep(.el-select__wrapper) {
  border-radius: 0;
  background: #f4f5f7;
  box-shadow: none !important;
}
.env-picker.is-seamless :deep(.el-select__wrapper.is-focused) {
  background: #eef1f5;
}
.env-option {
  display: flex;
  align-items: center;
  gap: 12px;
}
.env-option-name {
  flex-shrink: 0;
}
.env-option-url {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--ink-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
</style>
