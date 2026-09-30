<script setup lang="ts">
import { CircleCheckFilled, CircleCloseFilled } from '@element-plus/icons-vue'
import type { Threshold } from '../api'

// 阈值结果表：有效性检查和验收标准共用。
defineProps<{ thresholds: Threshold[] }>()
</script>

<template>
  <el-table :data="thresholds" size="small" class="threshold-table">
    <el-table-column label="结果" width="110">
      <template #default="{ row }">
        <span class="result" :class="row.ok ? 'is-ok' : 'is-bad'">
          <el-icon :size="16"><CircleCheckFilled v-if="row.ok" /><CircleCloseFilled v-else /></el-icon>
          {{ row.ok ? '通过' : '未通过' }}
        </span>
      </template>
    </el-table-column>
    <el-table-column label="检查项" min-width="240">
      <template #default="{ row }">{{ row.label || `${row.metric} ${row.expr}` }}</template>
    </el-table-column>
    <el-table-column label="k6 指标" min-width="180">
      <template #default="{ row }">
        <span class="mono">{{ row.metric }}</span>
      </template>
    </el-table-column>
    <el-table-column label="条件" min-width="140">
      <template #default="{ row }">
        <span class="mono">{{ row.expr }}</span>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped>
.result {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.result.is-ok {
  color: #1f8a3b;
}
.result.is-bad {
  color: #d03b3b;
}
</style>
