<script setup lang="ts">
import { computed, ref } from 'vue'
import { Delete, Plus, RefreshLeft } from '@element-plus/icons-vue'
import { useApiIndex } from '../../composables/useApiIndex'
import { useDebugContext } from '../../composables/useDebugContext'

// 一个被测环境的全部变量：初始值（存在环境上，压测用）、当前值（浏览器里，调试用，空着就用初始值）、
// 来源（环境定义 / 哪个接口提取）、被哪些接口引用。
const initial = defineModel<Record<string, string>>('initial', { default: () => ({}) })
const props = withDefaults(
  defineProps<{
    /** 显示和编辑这个环境的当前值；没有 id（新建中的环境）时不显示当前值列 */
    envId?: number | null
    /** 初始值可编辑（被测环境的编辑对话框里） */
    editInitial?: boolean
  }>(),
  { envId: null, editInitial: false },
)

const ctx = useDebugContext()
const index = useApiIndex()
const current = computed(() => (props.envId ? ctx.currentOf(props.envId) : {}))
const has = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k)

interface Row {
  name: string
  initial: string | null
  current: string | null
  producers: string[]
  usages: string[]
}
const rows = computed<Row[]>(() => {
  const names = [...Object.keys(initial.value)]
  const extra = new Set<string>()
  if (props.envId) Object.keys(current.value).forEach((n) => extra.add(n))
  Object.keys(index.producers.value).forEach((n) => extra.add(n))
  names.push(...[...extra].filter((n) => !has(initial.value, n)).sort())
  return names.map((name) => ({
    name,
    initial: has(initial.value, name) ? initial.value[name] : null,
    current: has(current.value, name) ? current.value[name] : null,
    producers: index.producers.value[name] ?? [],
    usages: index.usages.value[name] ?? [],
  }))
})
const changedCount = computed(() => Object.keys(current.value).length)

function setInitial(name: string, value: string): void {
  initial.value = { ...initial.value, [name]: value }
}
function removeInitial(name: string): void {
  const next = { ...initial.value }
  delete next[name]
  initial.value = next
}
function setCurrent(name: string, value: string): void {
  if (!props.envId) return
  if (value === '' && !has(current.value, name)) return
  ctx.setCurrent(props.envId, name, value)
}
function clearCurrent(name?: string): void {
  if (props.envId) ctx.clearCurrent(props.envId, name)
}

const newName = ref('')
const newValue = ref('')
const nameError = computed(() => {
  const n = newName.value.trim()
  if (!n) return ''
  if (!/^\w+$/.test(n)) return '只能用字母、数字、下划线'
  if (rows.value.some((r) => r.name === n)) return '已存在'
  return ''
})
function add(): void {
  const n = newName.value.trim()
  if (!n || nameError.value) return
  if (props.editInitial) setInitial(n, newValue.value)
  else setCurrent(n, newValue.value)
  newName.value = ''
  newValue.value = ''
}

void index.refresh()
</script>

<template>
  <div class="vars-table">
    <table>
      <thead>
        <tr>
          <th class="c-name">变量</th>
          <th>初始值</th>
          <th v-if="envId">当前值</th>
          <th class="c-source">来源</th>
          <th class="c-usage">引用</th>
          <th class="c-op">
            <el-button v-if="envId && changedCount" link type="primary" size="small" @click="clearCurrent()">全部恢复</el-button>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.name">
          <td class="c-name mono">{{ row.name }}</td>
          <td>
            <el-input
              v-if="editInitial && row.initial !== null"
              :model-value="row.initial"
              size="small"
              @update:model-value="setInitial(row.name, $event)"
            />
            <span v-else-if="row.initial !== null" class="mono">{{ row.initial }}</span>
            <span v-else class="muted">—</span>
          </td>
          <td v-if="envId">
            <el-input
              :model-value="row.current ?? ''"
              size="small"
              :class="{ 'is-changed': row.current !== null }"
              :placeholder="row.initial ?? (row.producers.length ? '未提取' : '')"
              @update:model-value="setCurrent(row.name, $event)"
            />
          </td>
          <td class="c-source">
            <el-tag v-if="row.initial !== null" size="small" type="info" effect="plain" disable-transitions>环境</el-tag>
            <el-tooltip v-if="row.producers.length" :content="`由 ${row.producers.join('、')} 提取`" placement="top">
              <el-tag size="small" effect="plain" class="tag-extract" disable-transitions>提取</el-tag>
            </el-tooltip>
          </td>
          <td class="c-usage">
            <el-tooltip v-if="row.usages.length" :content="row.usages.join('、')" placement="top">
              <span class="usage">{{ row.usages.length }}</span>
            </el-tooltip>
            <span v-else class="muted">0</span>
          </td>
          <td class="c-op">
            <el-button
              v-if="envId && row.current !== null"
              :icon="RefreshLeft"
              circle
              text
              size="small"
              title="恢复初始值"
              @click="clearCurrent(row.name)"
            />
            <el-button
              v-if="editInitial && row.initial !== null"
              :icon="Delete"
              circle
              text
              size="small"
              title="删除"
              @click="removeInitial(row.name)"
            />
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="envId ? 6 : 5" class="muted empty">暂无变量</td>
        </tr>
      </tbody>
    </table>
    <div class="add-row">
      <el-input v-model="newName" size="small" placeholder="变量名" class="mono add-name" @keyup.enter="add" />
      <el-input v-model="newValue" size="small" :placeholder="editInitial ? '初始值' : '当前值'" class="add-value" @keyup.enter="add" />
      <el-button :icon="Plus" size="small" :disabled="!newName.trim() || !!nameError" @click="add">添加</el-button>
      <span v-if="nameError" class="add-error">{{ nameError }}</span>
    </div>
  </div>
</template>

<style scoped>
.vars-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.vars-table th,
.vars-table td {
  padding: 4px 8px;
  border-bottom: 1px solid var(--hairline);
  text-align: left;
  vertical-align: middle;
}
.vars-table th {
  color: var(--ink-muted);
  font-weight: 400;
  font-size: 12px;
}
.c-name {
  width: 18%;
  word-break: break-all;
}
.c-source {
  width: 96px;
  white-space: nowrap;
}
.c-source .el-tag + .el-tag,
.c-source .el-tag + span .el-tag {
  margin-left: 4px;
}
.c-usage {
  width: 48px;
  text-align: center !important;
}
.c-op {
  width: 76px;
  text-align: right !important;
  white-space: nowrap;
}
.usage {
  color: var(--el-color-primary);
  cursor: default;
}
.tag-extract {
  --el-tag-text-color: #6a3fd1;
  --el-tag-border-color: rgba(124, 77, 255, 0.35);
  --el-tag-bg-color: rgba(124, 77, 255, 0.06);
}
.is-changed :deep(.el-input__inner) {
  color: #1d6fd6;
  font-weight: 600;
}
.empty {
  padding: 14px 8px;
  text-align: center !important;
}
.add-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.add-name {
  width: 18%;
}
.add-value {
  flex: 1;
}
.add-error {
  color: var(--el-color-danger);
  font-size: 12px;
}
</style>
