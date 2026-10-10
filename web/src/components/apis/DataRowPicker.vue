<script setup lang="ts">
import { computed } from 'vue'
import { Grid } from '@element-plus/icons-vue'
import { useDebugContext } from '../../composables/useDebugContext'
import { useDebugRows } from '../../composables/useDebugRows'

const ctx = useDebugContext()
const { choice, setChoice, datasets, refresh, dataset, problem, rowValues, ensureDetail } = useDebugRows()

function onDataset(id: number | null | undefined): void {
  if (typeof id !== 'number') setChoice(null)
  else setChoice({ datasetId: id, row: 0 })
  void ensureDetail()
}
function onRow(n: number | null | undefined): void {
  const d = dataset.value
  if (!d) return
  setChoice({ datasetId: d.id, row: Math.max(0, Math.round(n ?? 1) - 1) })
  void ensureDetail()
}
async function onShow(): Promise<void> {
  await refresh()
  void ensureDetail()
}
const rowNo = computed(() => (choice.value ? choice.value.row + 1 : 1))
</script>

<template>
  <el-popover placement="bottom-end" :width="380" trigger="click" @show="onShow">
    <template #reference>
      <span class="data-ref">
        <el-button
          :icon="Grid"
          :type="problem ? 'danger' : dataset ? 'primary' : undefined"
          :plain="!!dataset || !!problem"
          :disabled="!ctx.environment.value"
          :title="problem ?? undefined"
          class="data-btn"
        >
          <template v-if="dataset">
            <span class="data-btn-name">{{ dataset.name }}</span>
            <span class="num">#{{ rowNo }}</span>
          </template>
          <template v-else>数据</template>
        </el-button>
      </span>
    </template>
    <div class="data-pick">
      <!-- 下拉不传送到 body：否则点选项算点在弹层外面，弹层会关掉 -->
      <el-select
        :model-value="dataset?.id"
        :teleported="false"
        clearable
        filterable
        placeholder="不使用数据集"
        no-data-text="还没有数据集"
        @update:model-value="onDataset"
      >
        <el-option v-for="d in datasets" :key="d.id" :label="d.name" :value="d.id">
          <span class="data-option">
            <span>{{ d.name }}</span>
            <span class="muted num">{{ d.rowCount }} 行</span>
          </span>
        </el-option>
      </el-select>
      <div v-if="dataset" class="data-row-line">
        <span class="muted">行</span>
        <el-input-number
          :model-value="rowNo"
          :min="1"
          :max="Math.max(1, dataset.rowCount)"
          :precision="0"
          controls-position="right"
          size="small"
          @update:model-value="onRow"
        />
        <span class="muted num">/ {{ dataset.rowCount }}</span>
        <span v-if="problem" class="data-problem">{{ problem }}</span>
      </div>
      <table v-if="rowValues" class="data-values">
        <tbody>
          <tr v-for="(value, column) in rowValues" :key="column">
            <th class="mono">{{ column }}</th>
            <td class="mono">{{ value }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="dataset" class="data-columns mono">{{ dataset.columns.join('  ') }}</div>
    </div>
  </el-popover>
</template>

<style scoped>
.data-ref {
  display: inline-flex;
}
.data-btn-name {
  display: inline-block;
  max-width: 7em;
  margin-right: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.data-pick .el-select {
  width: 100%;
}
.data-option {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.data-row-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}
.data-problem {
  color: var(--el-color-danger);
  font-size: 12px;
}
.data-values {
  width: 100%;
  margin-top: 10px;
  border-collapse: collapse;
  font-size: 12.5px;
}
.data-values th,
.data-values td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--hairline);
  text-align: left;
  word-break: break-all;
}
.data-values th {
  width: 40%;
  color: var(--el-text-color-regular);
  font-weight: 500;
}
.data-columns {
  margin-top: 10px;
  color: var(--ink-muted);
  word-break: break-all;
}
</style>
