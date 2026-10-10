<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, DocumentCopy, Plus, Position, RefreshLeft } from '@element-plus/icons-vue'
import type { ApiDef, BrokenRef, ExtractFrom, Usage } from '../../api'
import { useApiIndex } from '../../composables/useApiIndex'
import { useDebug } from '../../composables/useDebug'
import { useDebugContext } from '../../composables/useDebugContext'
import { useDebugRows } from '../../composables/useDebugRows'
import { useFileList } from '../../composables/useFileList'
import { formProblem, isBlankRow, toInput, type ApiForm } from '../../utils/api-form'
import type { FolderOption } from '../../utils/folders'
import { copyText } from '../../utils/clipboard'
import { buildCurl } from '../../utils/curl'
import { STEP_STATUS } from '../../utils/debug'
import { formatMs } from '../../utils/format'
import { STATUS_STYLE, statusKind, statusLabel } from '../../utils/http-status'
import type { KvRow } from '../../utils/kv'
import { METHODS, METHOD_COLOR } from '../../utils/method'
import { joinPath, splitPath } from '../../utils/query'
import { apiRefs } from '../../utils/var-sources'
import { isDynamicRef, isValidVarName } from '../../utils/vars'
import KeyValueEditor from '../KeyValueEditor.vue'
import VarInput from '../VarInput.vue'
import DebugErrorView from '../debug/DebugErrorView.vue'
import DebugStepPanel from '../debug/DebugStepPanel.vue'
import VariablesTable from '../debug/VariablesTable.vue'
import EnvPicker from '../debug/EnvPicker.vue'
import BodyEditor from './BodyEditor.vue'
import BrokenTag from '../refs/BrokenTag.vue'
import UsageTag from '../refs/UsageTag.vue'
import DataRowPicker from './DataRowPicker.vue'
import UpstreamPicker, { type UpstreamCandidate } from './UpstreamPicker.vue'

const form = defineModel<ApiForm>({ required: true })
const props = defineProps<{
  /** 正在编辑的已保存接口；新建时为 null */
  apiId: number | null
  isNew: boolean
  dirty: boolean
  saving: boolean
  /** 已保存接口的自动保存状态 */
  saveStatus: 'saving' | 'saved' | 'error' | null
  saveError: string
  /** 标准的引用字段（契约 §3.8） */
  usedBy: Usage[]
  brokenRefs: BrokenRef[]
  folderOptions: FolderOption[]
  producers: Record<string, string[]>
}>()
const emit = defineEmits<{ save: []; duplicate: []; delete: [] }>()

const ctx = useDebugContext()
/** 变量表里改初始值：立即保存到当前调试环境上 */
const envInitial = computed({
  get: () => ctx.initialVars.value,
  set: (v: Record<string, string>) => {
    if (ctx.environment.value) ctx.setInitialVars(ctx.environment.value.id, v)
  },
})
const index = useApiIndex()
const dataRows = useDebugRows()
const { files } = useFileList()
const { running, result, error, run, reset } = useDebug()

// 换了一个接口（父组件换了对象）：上一次的响应不再对应
watch(
  () => form.value,
  () => reset(),
)

const queryRows = ref<KvRow[]>(splitPath(form.value.path).rows)
let syncingFromRows = false
watch(
  () => form.value.path,
  (path) => {
    if (!syncingFromRows) queryRows.value = splitPath(path).rows
  },
  { flush: 'sync' },
)
function onQueryRows(rows: KvRow[]): void {
  queryRows.value = rows
  syncingFromRows = true
  try {
    form.value.path = joinPath(splitPath(form.value.path).pathname, rows)
  } finally {
    syncingFromRows = false
  }
}

const tab = ref('params')
const queryCount = computed(() => queryRows.value.filter((r) => r.key.trim() !== '').length)

/** 当前调试环境的公共请求头：只读显示，接口里同名（不区分大小写）的会覆盖它 */
// 环境请求头和接口请求头合成一张可编辑的表：改环境行的值 = 在接口里加一条同名请求头覆盖它（只影响本接口）；
// 删除覆盖行 = 恢复继承。名称比较不区分大小写，和引擎的合并规则一致。
interface HeaderRow {
  rowKey: string
  source: 'env' | 'override' | 'own'
  key: string
  value: string
  /** form.headers 里的下标；env 行没有 */
  index: number
}
const headerRows = computed<HeaderRow[]>(() => {
  const own = form.value.headers
  const lower = (k: string) => k.trim().toLowerCase()
  const used = new Set<number>()
  const rows: HeaderRow[] = []
  for (const [name, value] of Object.entries(ctx.environment.value?.headers ?? {})) {
    const i = own.findIndex((r) => lower(r.key) === name.toLowerCase())
    if (i >= 0) {
      used.add(i)
      rows.push({ rowKey: `env-${name.toLowerCase()}`, source: 'override', key: own[i].key, value: own[i].value, index: i })
    } else {
      rows.push({ rowKey: `env-${name.toLowerCase()}`, source: 'env', key: name, value, index: -1 })
    }
  }
  own.forEach((r, i) => {
    if (!used.has(i)) rows.push({ rowKey: `own-${i}`, source: 'own', key: r.key, value: r.value, index: i })
  })
  return rows
})
const headerTotal = computed(() => headerRows.value.filter((r) => r.key.trim() !== '').length)

function setHeader(row: HeaderRow, field: 'key' | 'value', text: string): void {
  if (row.source === 'env') {
    form.value.headers.push({ key: row.key, value: field === 'value' ? text : row.value })
  } else {
    form.value.headers[row.index] = { ...form.value.headers[row.index], [field]: text }
  }
}
function removeHeader(row: HeaderRow): void {
  if (row.index >= 0) form.value.headers.splice(row.index, 1)
}
function addHeader(): void {
  form.value.headers.push({ key: '', value: '' })
}
const extractCount = computed(() => form.value.extracts.filter((e) => e.var.trim() !== '' || e.expr.trim() !== '').length)
const hasBody = computed(() => {
  const f = form.value
  if (f.bodyMode === 'raw') return f.body !== ''
  if (f.bodyMode === 'form' || f.bodyMode === 'multipart') return f.form.some((r) => !isBlankRow(r))
  return false
})

/** 变量高亮：环境的初始值和当前值，加上选中的数据行（层次在它们之上） */
const editorVars = computed<Record<string, string>>(() => ({ ...ctx.vars.value, ...(dataRows.rowValues.value ?? {}) }))
const editorHints = computed(() => dataRows.hints.value)
watch(dataRows.dataset, () => void dataRows.ensureDetail(), { immediate: true })
// 记住的选择要先有数据集列表才能显示、高亮和发送
watch(
  dataRows.choice,
  (c) => {
    if (c && !dataRows.loaded.value) void dataRows.refresh(true)
  },
  { immediate: true },
)

const EXTRACT_SOURCES: { value: ExtractFrom; label: string }[] = [
  { value: 'json', label: 'JSON 路径' },
  { value: 'regex', label: '正则（第 1 个捕获组）' },
  { value: 'header', label: '响应头' },
  { value: 'cookie', label: 'Cookie' },
]
function extractPlaceholder(from: ExtractFrom): string {
  if (from === 'json') return 'data.items.0.id'
  if (from === 'regex') return '"token":"([^"]+)"'
  if (from === 'cookie') return 'SESSIONID'
  return 'X-Request-Id'
}
function regexError(from: ExtractFrom, expr: string): string | null {
  if (from !== 'regex' || !expr.trim()) return null
  try {
    new RegExp(expr.trim())
    return null
  } catch (e) {
    return e instanceof Error ? e.message : String(e)
  }
}
function varNameError(name: string): string | null {
  const n = name.trim()
  if (!n || isValidVarName(n)) return null
  return '变量名只能用字母（含中文）、数字、下划线'
}
function addExtract(): void {
  form.value.extracts.push({ var: '', from: 'json', expr: '' })
}

/** 本接口引用的变量（含环境公共请求头里的），不含动态变量 */
const refNames = computed(() =>
  apiRefs(toInput(form.value), ctx.environment.value?.headers ?? {}).filter((n) => !isDynamicRef(n)),
)
const has = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k)
const otherProducers = (name: string): ApiDef[] =>
  (index.producerApis.value[name] ?? []).filter((api) => api.id !== props.apiId)

const upstream = ref<number[]>([])
watch(
  () => props.apiId,
  (id, old) => {
    if (id !== old) upstream.value = []
  },
)
const upstreamCandidates = computed<UpstreamCandidate[]>(() => {
  const map = new Map<number, UpstreamCandidate>()
  for (const name of refNames.value) {
    for (const api of otherProducers(name)) {
      const entry = map.get(api.id) ?? { api, vars: [] }
      entry.vars.push(name)
      map.set(api.id, entry)
    }
  }
  for (const id of upstream.value) {
    const api = index.apis.value.find((a) => a.id === id)
    if (api && !map.has(id)) map.set(id, { api, vars: [] })
  }
  return [...map.values()]
})
const pendingVars = computed(() =>
  refNames.value.filter(
    (n) => !has(editorVars.value, n) && !has(editorHints.value, n) && otherProducers(n).length > 0,
  ),
)

const sendBlocker = computed<string | null>(() => {
  if (ctx.blocker.value) return ctx.blocker.value
  if (!form.value.path.trim().startsWith('/')) return '路径必须以 / 开头'
  return formProblem(form.value) ?? dataRows.problem.value
})

async function send(): Promise<void> {
  const env = ctx.environment.value
  if (!env || sendBlocker.value || running.value) return
  if (!(await ctx.ensureProdConfirmed())) return
  const input = toInput(form.value)
  if (!input.name) input.name = '未命名接口'
  const known = new Set(index.apis.value.map((a) => a.id))
  const before = index.apis.value.length ? upstream.value.filter((id) => known.has(id)) : [...upstream.value]
  const rows = dataRows.rowsParam.value
  const r = await run({
    envId: env.id,
    ...(env.type === 'prod' ? { confirmProd: true } : {}),
    vars: ctx.overrides.value,
    api: input,
    ...(before.length ? { beforeApiIds: before } : {}),
    ...(rows ? { rows } : {}),
  })
  updatedVars.value = r ? ctx.applyExtracted(r) : []
  upstreamOpen.value = r ? r.steps.slice(0, -1).filter((s) => s.status !== 'passed').map((s) => s.key) : []
}
const updatedVars = ref<string[]>([])
/** 最后一步是目标接口，前面的是上游 */
const step = computed(() => result.value?.steps.at(-1) ?? null)
const upstreamSteps = computed(() => result.value?.steps.slice(0, -1) ?? [])
const upstreamOpen = ref<string[]>([])

function onKey(e: KeyboardEvent): void {
  if (!(e.ctrlKey || e.metaKey)) return
  if (e.key === 'Enter') {
    e.preventDefault()
    void send()
  } else if (e.key.toLowerCase() === 's') {
    e.preventDefault()
    emit('save')
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

async function copyCurl(): Promise<void> {
  const env = ctx.environment.value
  const text = buildCurl(toInput(form.value), env?.baseUrl ?? 'https://被测环境地址', env?.headers ?? {}, files.value)
  if (await copyText(text)) {
    ElMessage.success(env ? '已复制 cURL 命令' : '已复制 cURL 命令（没有选被测环境，地址是占位符）')
    return
  }
  await ElMessageBox.alert(h('pre', { class: 'curl-text' }, text), '复制下面的命令', { confirmButtonText: '关闭' }).catch(
    () => undefined,
  )
}
</script>

<template>
  <div class="editor">
    <div class="editor-head">
      <el-input v-model="form.name" class="name-input" placeholder="接口名称，例如：查询订单" maxlength="100" />
      <el-tree-select
        v-model="form.folderId"
        :data="folderOptions"
        check-strictly
        default-expand-all
        clearable
        :value-on-clear="null"
        placeholder="根目录"
        class="folder-select"
        title="所属文件夹"
        :disabled="!folderOptions.length"
      />
      <span v-if="isNew && dirty" class="unsaved">未保存</span>
      <el-tooltip v-else-if="saveStatus === 'error'" :content="saveError" placement="bottom">
        <span class="unsaved">未保存</span>
      </el-tooltip>
      <span v-else-if="saveStatus === 'saving'" class="save-state">保存中</span>
      <span v-else-if="saveStatus === 'saved' && !dirty" class="save-state">已保存</span>
      <UsageTag :usages="usedBy" />
      <BrokenTag :refs="brokenRefs" />
      <div class="editor-actions">
        <el-button text :icon="DocumentCopy" @click="copyCurl">复制为 cURL</el-button>
        <el-button v-if="!isNew" text :icon="CopyDocument" @click="emit('duplicate')">复制接口</el-button>
        <el-button v-if="!isNew" text type="danger" :icon="Delete" @click="emit('delete')">删除</el-button>
      </div>
    </div>

    <div class="request-bar">
      <el-select v-model="form.method" class="method-select" :style="{ '--method-color': METHOD_COLOR[form.method] }">
        <el-option v-for="m in METHODS" :key="m" :value="m" :label="m">
          <span :style="{ color: METHOD_COLOR[m], fontWeight: 700 }">{{ m }}</span>
        </el-option>
      </el-select>
      <div class="url-box">
        <EnvPicker seamless class="url-env" />
        <VarInput
          v-model="form.path"
          class="url-path"
          seamless
          :vars="editorVars"
          :producers="producers"
          :hints="editorHints"
          placeholder="/api/orders/{{orderId}}?page=1"
        />
      </div>
      <DataRowPicker />
      <div class="send-group">
        <el-tooltip :content="sendBlocker ?? 'Ctrl + Enter'" placement="bottom">
          <span class="send-main">
            <el-button type="primary" :icon="Position" :loading="running" :disabled="!!sendBlocker" @click="send">
              {{ running ? '发送中' : '发送' }}
            </el-button>
          </span>
        </el-tooltip>
        <UpstreamPicker v-model="upstream" :candidates="upstreamCandidates" :pending="pendingVars" />
      </div>
      <el-tooltip v-if="isNew" content="Ctrl + S" placement="bottom">
        <el-button :loading="saving" :disabled="!dirty" @click="emit('save')">保存</el-button>
      </el-tooltip>
    </div>

    <el-tabs v-model="tab" class="req-tabs">
      <el-tab-pane name="params">
        <template #label>参数<span v-if="queryCount" class="tab-count">{{ queryCount }}</span></template>
        <KeyValueEditor
          :vars="editorVars"
          :producers="producers"
          :hints="editorHints"
          :model-value="queryRows"
          key-placeholder="参数名"
          value-placeholder="值，可以用 {{变量名}}"
          add-text="添加参数"
          @update:model-value="onQueryRows"
        />
      </el-tab-pane>

      <el-tab-pane name="headers">
        <template #label>请求头<span v-if="headerTotal" class="tab-count">{{ headerTotal }}</span></template>
        <div class="row-list">
          <div v-for="row in headerRows" :key="row.rowKey" class="row-item header-row" :class="`is-${row.source}`">
            <el-input
              :model-value="row.key"
              :readonly="row.source !== 'own'"
              placeholder="名称"
              style="width: 34%"
              @update:model-value="setHeader(row, 'key', $event)"
            />
            <div class="grow">
              <VarInput
                :model-value="row.value"
                :vars="editorVars"
                :producers="producers"
                :hints="editorHints"
                placeholder="值"
                @update:model-value="setHeader(row, 'value', $event)"
              />
            </div>
            <span class="header-source">
              <el-tag
                v-if="row.source !== 'own'"
                :key="row.source"
                disable-transitions
                size="small"
                :type="row.source === 'env' ? 'info' : 'warning'"
                effect="plain"
              >
                {{ row.source === 'env' ? '环境' : '覆盖环境' }}
              </el-tag>
            </span>
            <el-button
              v-if="row.source === 'override'"
              :icon="RefreshLeft"
              circle
              text
              title="恢复继承"
              @click="removeHeader(row)"
            />
            <el-button v-else-if="row.source === 'own'" :icon="Delete" circle text title="删除" @click="removeHeader(row)" />
            <span v-else class="header-action-placeholder" />
          </div>
          <el-button :icon="Plus" size="small" @click="addHeader">添加请求头</el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane name="body">
        <template #label>请求体<span v-if="hasBody" class="tab-dot" /></template>
        <BodyEditor
          v-model="form"
          :vars="editorVars"
          :producers="producers"
          :hints="editorHints"
          :env-headers="ctx.environment.value?.headers ?? {}"
        />
      </el-tab-pane>

      <el-tab-pane name="expect" label="期望">
        <el-form label-width="130px" class="expect-form">
          <el-form-item label="期望状态码">
            <el-input-number v-model="form.expectStatus" :min="100" :max="599" :precision="0" controls-position="right" />
          </el-form-item>
          <el-form-item label="期望包含的文本">
            <VarInput
              v-model="form.expectBodyContains"
              :vars="editorVars"
              :producers="producers"
              :hints="editorHints"
              placeholder="留空表示不检查响应内容"
            />
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane name="extract">
        <template #label>变量提取<span v-if="extractCount" class="tab-count">{{ extractCount }}</span></template>
        <div class="row-list">
          <div v-for="(item, index) in form.extracts" :key="index" class="row-item">
            <el-input
              v-model="item.var"
              placeholder="变量名"
              style="width: 160px"
              class="mono"
              :class="{ 'is-invalid': varNameError(item.var) }"
              :title="varNameError(item.var) ?? undefined"
            />
            <el-select v-model="item.from" style="width: 180px">
              <el-option v-for="s in EXTRACT_SOURCES" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
            <el-input
              v-model="item.expr"
              class="grow mono"
              :class="{ 'is-invalid': regexError(item.from, item.expr) }"
              :title="regexError(item.from, item.expr) ?? undefined"
              :placeholder="extractPlaceholder(item.from)"
            />
            <el-button :icon="Delete" circle text title="删除这一条" @click="form.extracts.splice(index, 1)" />
          </div>
          <el-button :icon="Plus" size="small" @click="addExtract">添加提取规则</el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane name="note" label="备注">
        <el-input v-model="form.note" type="textarea" :rows="3" placeholder="这个接口是做什么的、注意事项" />
      </el-tab-pane>

      <el-tab-pane name="vars">
        <template #label>环境变量<span v-if="ctx.varCount.value" class="tab-count">{{ ctx.varCount.value }}</span></template>
        <VariablesTable v-if="ctx.environment.value" v-model:initial="envInitial" :env-id="ctx.environment.value.id" confirm-delete />
        <span v-else class="muted">未选择环境</span>
      </el-tab-pane>
    </el-tabs>

    <section class="response">
      <div class="response-head">
        <span class="response-title">响应</span>
        <span v-if="result && updatedVars.length" class="vars-updated">
          已更新变量 <span class="mono">{{ updatedVars.join('、') }}</span>
        </span>
      </div>
      <div v-if="running" class="response-empty">发送中…</div>
      <DebugErrorView v-else-if="error" :error="error" />
      <template v-else-if="step">
        <el-collapse v-if="upstreamSteps.length" v-model="upstreamOpen" class="upstream-steps">
          <el-collapse-item v-for="(s, i) in upstreamSteps" :key="s.key" :name="s.key">
            <template #title>
              <span class="upstream-title">
                <span class="upstream-no">上游 {{ i + 1 }}</span>
                <el-tag :type="STEP_STATUS[s.status].tag" size="small" effect="dark" disable-transitions>
                  {{ STEP_STATUS[s.status].label }}
                </el-tag>
                <span class="upstream-name">{{ s.name }}</span>
                <span
                  v-if="s.response"
                  class="upstream-status"
                  :style="{ color: STATUS_STYLE[statusKind(s.response.status)].color }"
                >
                  {{ statusLabel(s.response.status, s.response.statusText) }}
                </span>
                <span v-if="s.timings" class="num muted upstream-ms">{{ formatMs(s.timings.durationMs) }}</span>
              </span>
            </template>
            <DebugStepPanel :step="s" />
          </el-collapse-item>
        </el-collapse>
        <DebugStepPanel :step="step" />
      </template>
      <div v-else class="response-empty">点击发送查看响应</div>
    </section>
  </div>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 18px 24px;
}
.editor-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.name-input {
  flex: 1;
  min-width: 0;
  --el-input-border-color: transparent;
  --el-input-hover-border-color: var(--hairline);
  font-size: 16px;
  font-weight: 600;
}
.name-input :deep(.el-input__inner) {
  font-size: 16px;
  font-weight: 600;
}
.folder-select {
  width: 200px;
  flex-shrink: 0;
}
.save-state {
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.unsaved {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 10px;
  background: #fdf0e1;
  color: #d9730d;
  font-size: 12px;
}
.editor-actions {
  display: flex;
  flex-shrink: 0;
}
.editor-actions .el-button + .el-button {
  margin-left: 0;
}

/* 请求栏：方法 + 一条完整地址（环境前缀 + 路径）+ 动作 */
.request-bar {
  display: flex;
  align-items: stretch;
  gap: 8px;
}
.method-select {
  width: 118px;
  flex-shrink: 0;
}
.method-select :deep(.el-select__selected-item) {
  color: var(--method-color);
  font-weight: 700;
  letter-spacing: 0.3px;
}
.url-box {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: stretch;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
  background: #fff;
  overflow: hidden;
}
.url-box:focus-within {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}
.url-env {
  flex: 0 1 auto;
  min-width: 130px;
  border-right: 1px solid var(--hairline);
}
.url-path {
  flex: 1 0 200px;
  min-width: 0;
  align-self: center;
}
.request-bar .el-button + .el-button {
  margin-left: 0;
}
.send-group {
  display: inline-flex;
  flex-shrink: 0;
}
.send-main :deep(.el-button) {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}

.req-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.tab-count {
  margin-left: 5px;
  color: var(--ink-muted);
  font-size: 12px;
}
.tab-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-left: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
  vertical-align: middle;
}
.row-item .is-invalid :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.expect-form {
  max-width: 640px;
}

.header-row.is-env :deep(.el-input__wrapper) {
  background: #fafbfc;
}
.header-row.is-env :deep(.el-input__inner),
.header-row :deep(.el-input__inner[readonly]) {
  color: var(--el-text-color-regular);
}
.header-source {
  width: 72px;
  flex-shrink: 0;
}
.header-action-placeholder {
  width: 32px;
  flex-shrink: 0;
}
.vars-updated {
  color: #1f8a3b;
  font-size: 12px;
}
.response {
  padding-top: 14px;
  border-top: 1px solid var(--hairline);
}
.response-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 10px;
}
.response-title {
  font-size: 15px;
  font-weight: 600;
}
.response-meta {
  font-size: 12px;
}
.upstream-steps {
  margin-bottom: 12px;
  border-top: none;
}
.upstream-steps :deep(.el-collapse-item__header) {
  height: 36px;
  line-height: 36px;
}
.upstream-steps :deep(.el-collapse-item__content) {
  padding: 4px 8px 12px;
}
.upstream-title {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding-right: 12px;
  font-size: 13px;
}
.upstream-no {
  flex-shrink: 0;
  color: var(--ink-muted);
  font-size: 12px;
}
.upstream-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.upstream-status {
  flex-shrink: 0;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.upstream-ms {
  margin-left: auto;
  flex-shrink: 0;
}
.response-empty {
  padding: 26px 12px;
  border: 1px dashed var(--hairline);
  border-radius: 8px;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.6;
  text-align: center;
}
</style>
