<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowRight, Delete, Plus, RefreshLeft, Upload } from '@element-plus/icons-vue'
import { useApiIndex } from '../../composables/useApiIndex'
import { useDebugContext } from '../../composables/useDebugContext'
import { copyText } from '../../utils/clipboard'
import { confirmAction } from '../../utils/feedback'
import { DYNAMIC_VARS, isValidVarName } from '../../utils/vars'

// 一个被测环境的变量：环境里定义的（有初始值，存在库里，正式运行用）加上本机有当前值的（调试用，
// 提取到的变量写在这里）。初始值的改动交给 v-model 的使用方保存：被测环境对话框随对话框保存，
// 接口页和页头的变量表立即保存到环境上
const initial = defineModel<Record<string, string>>('initial', { default: () => ({}) })
const props = withDefaults(
  defineProps<{
    /** 显示和编辑这个环境的当前值；没有 id（新建中的环境）时不显示当前值列 */
    envId?: number | null
    /** 删除环境里定义的变量前确认（改动立即保存到环境上时） */
    confirmDelete?: boolean
  }>(),
  { envId: null, confirmDelete: false },
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
  if (props.envId) names.push(...Object.keys(current.value).filter((n) => !has(initial.value, n)).sort())
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
/** 把当前值保存成初始值：从此正式运行也用它 */
function persist(row: Row): void {
  if (row.current === null) return
  setInitial(row.name, row.current)
  clearCurrent(row.name)
}
async function remove(row: Row): Promise<void> {
  if (row.initial !== null) {
    if (props.confirmDelete && !(await confirmAction(`删除变量 ${row.name}？被测环境里的初始值也会删除，正式运行不再有它。`, '删除变量', true))) return
    removeInitial(row.name)
  }
  clearCurrent(row.name)
}

const newName = ref('')
const newValue = ref('')
const nameError = computed(() => {
  const n = newName.value.trim()
  if (!n) return ''
  if (!isValidVarName(n)) return '只能用字母（含中文）、数字、下划线'
  if (rows.value.some((r) => r.name === n)) return '已存在'
  return ''
})
function add(): void {
  const n = newName.value.trim()
  if (!n || nameError.value) return
  setInitial(n, newValue.value)
  newName.value = ''
  newValue.value = ''
}

const dynamicOpen = ref(false)
async function copyExample(text: string): Promise<void> {
  if (await copyText(text)) ElMessage.success(`已复制 ${text}`)
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
              :model-value="row.initial ?? ''"
              size="small"
              :placeholder="row.initial === null ? '无' : ''"
              @update:model-value="setInitial(row.name, $event)"
            />
          </td>
          <td v-if="envId">
            <el-input
              :model-value="row.current ?? ''"
              size="small"
              :class="{ 'is-changed': row.current !== null }"
              :placeholder="row.initial ?? ''"
              @update:model-value="setCurrent(row.name, $event)"
            />
          </td>
          <td class="c-source">
            <el-tag v-if="row.initial !== null" size="small" type="info" effect="plain" disable-transitions>环境</el-tag>
            <el-tooltip v-if="row.producers.length" :content="`由 ${row.producers.join('、')} 提取`" placement="top">
              <el-tag size="small" effect="plain" class="tag-extract" disable-transitions>提取</el-tag>
            </el-tooltip>
            <el-tag v-if="row.initial === null && !row.producers.length" size="small" effect="plain" disable-transitions>本机</el-tag>
          </td>
          <td class="c-usage">
            <el-tooltip v-if="row.usages.length" :content="row.usages.join('、')" placement="top">
              <span class="usage">{{ row.usages.length }}</span>
            </el-tooltip>
            <span v-else class="muted">0</span>
          </td>
          <td class="c-op">
            <el-button
              v-if="envId && row.current !== null && row.current !== row.initial"
              :icon="Upload"
              circle
              text
              size="small"
              title="设为初始值"
              @click="persist(row)"
            />
            <el-button
              v-if="envId && row.current !== null && row.initial !== null"
              :icon="RefreshLeft"
              circle
              text
              size="small"
              title="恢复初始值"
              @click="clearCurrent(row.name)"
            />
            <el-button :icon="Delete" circle text size="small" title="删除" @click="remove(row)" />
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="envId ? 6 : 5" class="muted empty">暂无变量</td>
        </tr>
      </tbody>
    </table>
    <div class="add-row">
      <el-input v-model="newName" size="small" placeholder="变量名" class="mono add-name" @keyup.enter="add" />
      <el-input v-model="newValue" size="small" placeholder="初始值" class="add-value" @keyup.enter="add" />
      <el-button :icon="Plus" size="small" :disabled="!newName.trim() || !!nameError" @click="add">添加</el-button>
      <span v-if="nameError" class="add-error">{{ nameError }}</span>
    </div>
    <div class="dynamic">
      <button type="button" class="dynamic-toggle" @click="dynamicOpen = !dynamicOpen">
        <el-icon><ArrowDown v-if="dynamicOpen" /><ArrowRight v-else /></el-icon>动态变量
      </button>
      <table v-if="dynamicOpen" class="dynamic-table">
        <tbody>
          <tr v-for="d in DYNAMIC_VARS" :key="d.name" :title="d.meaning">
            <td class="mono dynamic-name">
              {{ d.name }}<span v-if="d.aliases" class="muted">（{{ d.aliases.join('、') }}）</span>
            </td>
            <td>
              <button type="button" class="mono dynamic-example" @click="copyExample(d.example)">{{ d.example }}</button>
            </td>
          </tr>
        </tbody>
      </table>
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
  width: 104px;
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
.dynamic {
  margin-top: 10px;
}
.dynamic-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--ink-muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.dynamic-toggle:hover {
  color: var(--el-color-primary);
}
.vars-table .dynamic-table {
  margin-top: 4px;
}
.vars-table .dynamic-table td {
  padding: 3px 8px;
}
.dynamic-name {
  width: 18%;
  white-space: nowrap;
}
.dynamic-example {
  padding: 0;
  border: 0;
  background: none;
  color: #1d6fd6;
  cursor: copy;
}
.dynamic-example:hover {
  text-decoration: underline;
}
</style>
