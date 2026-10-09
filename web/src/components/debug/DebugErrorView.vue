<script setup lang="ts">
import { computed } from 'vue'
import type { ApiError } from '../../api'

// 调试没有拿到结果时的展示：预检被拒、有运行在进行、k6 没产出记录。
// k6 失败时 details 是日志的最后几行，用等宽文本整块显示；其余情况逐条列出。
const props = defineProps<{ error: ApiError }>()

const isLog = computed(() => props.error.code === 'DEBUG_FAILED')
const title = computed(() => {
  if (props.error.status === 409) return props.error.message || '现在不能调试'
  if (props.error.status === 422) return props.error.message || '预检不通过，没有发送'
  return props.error.message || '调试失败'
})
</script>

<template>
  <el-alert type="error" :closable="false" show-icon :title="title" class="debug-error">
    <template v-if="error.details.length">
      <pre v-if="isLog" class="debug-error-log">{{ error.details.join('\n') }}</pre>
      <ul v-else class="debug-error-list">
        <li v-for="(item, index) in error.details" :key="index">{{ item }}</li>
      </ul>
    </template>
  </el-alert>
</template>

<style scoped>
.debug-error-list {
  margin: 4px 0 0;
  padding-left: 18px;
  line-height: 1.8;
}
.debug-error-log {
  max-height: 320px;
  margin: 8px 0 0;
  padding: 10px 12px;
  overflow: auto;
  border-radius: 6px;
  background: #2b2f36;
  color: #e6e8ec;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
