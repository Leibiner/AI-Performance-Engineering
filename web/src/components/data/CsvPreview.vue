<script setup lang="ts">
import type { DatasetSource } from '../../api'
import { formatCount } from '../../utils/format'
import { delimiterLabel, encodingLabel } from '../../utils/test-data'

defineProps<{
  columns: string[]
  rows: string[][]
  rowCount: number
  source: DatasetSource | null
}>()
</script>

<template>
  <div class="csv-preview">
    <div class="csv-meta">
      <span><strong class="num">{{ formatCount(rowCount) }}</strong> 行</span>
      <span><strong class="num">{{ columns.length }}</strong> 列</span>
      <template v-if="source">
        <span>编码 {{ encodingLabel(source.encoding) }}</span>
        <span>分隔符 {{ delimiterLabel(source.delimiter) }}</span>
        <span v-if="source.fileName" class="mono">{{ source.fileName }}</span>
      </template>
      <span v-if="rowCount > rows.length" class="muted">前 {{ rows.length }} 行</span>
    </div>
    <div class="csv-table-wrap">
      <table class="csv-table">
        <thead>
          <tr>
            <th class="csv-index">#</th>
            <th v-for="c in columns" :key="c" class="mono">{{ c }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in rows" :key="i">
            <td class="csv-index num">{{ i + 1 }}</td>
            <td v-for="(_, j) in columns" :key="j" class="mono">{{ row[j] ?? '' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.csv-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin-bottom: 6px;
  color: var(--el-text-color-regular);
  font-size: 13px;
}
.csv-table-wrap {
  max-height: 320px;
  overflow: auto;
  border: 1px solid var(--hairline);
  border-radius: 6px;
}
.csv-table {
  min-width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.csv-table th,
.csv-table td {
  padding: 4px 10px;
  border-bottom: 1px solid var(--hairline);
  text-align: left;
  white-space: pre;
}
.csv-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f4f5f7;
  font-weight: 600;
}
.csv-index {
  width: 1%;
  color: var(--ink-muted);
  text-align: right !important;
}
</style>
