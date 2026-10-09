<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, DocumentCopy, Plus, Position } from '@element-plus/icons-vue'
import type { ExtractFrom } from '../../api'
import { useDebug } from '../../composables/useDebug'
import { useDebugContext } from '../../composables/useDebugContext'
import { toInput, type ApiForm } from '../../utils/api-form'
import type { FolderOption } from '../../utils/folders'
import { buildCurl } from '../../utils/curl'
import { tryPrettyJson } from '../../utils/debug'
import type { KvRow } from '../../utils/kv'
import { METHODS, METHOD_COLOR } from '../../utils/method'
import { joinPath, splitPath } from '../../utils/query'
import KeyValueEditor from '../KeyValueEditor.vue'
import DebugErrorView from '../debug/DebugErrorView.vue'
import DebugStepPanel from '../debug/DebugStepPanel.vue'
import DebugVarsEditor from '../debug/DebugVarsEditor.vue'
import EnvPicker from '../debug/EnvPicker.vue'

const form = defineModel<ApiForm>({ required: true })
defineProps<{ isNew: boolean; dirty: boolean; saving: boolean; folderOptions: FolderOption[] }>()
const emit = defineEmits<{ save: []; duplicate: []; delete: [] }>()

const ctx = useDebugContext()
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
const headerCount = computed(() => form.value.headers.filter((r) => r.key.trim() !== '').length)

/** 当前调试环境的公共请求头：只读显示，接口里同名（不区分大小写）的会覆盖它 */
const inheritedHeaders = computed(() => {
  const own = new Set(form.value.headers.map((r) => r.key.trim().toLowerCase()).filter(Boolean))
  return Object.entries(ctx.environment.value?.headers ?? {}).map(([name, value]) => ({
    name,
    value,
    overridden: own.has(name.toLowerCase()),
  }))
})
const extractCount = computed(() => form.value.extracts.filter((e) => e.var.trim() !== '' || e.expr.trim() !== '').length)
const bodyIsJsonLike = computed(() => /^\s*[[{]/.test(form.value.body))

function formatBody(): void {
  const pretty = tryPrettyJson(form.value.body)
  if (pretty) form.value.body = pretty
  else ElMessage.warning('请求体不是合法的 JSON，没有改动')
}

const EXTRACT_SOURCES: { value: ExtractFrom; label: string }[] = [
  { value: 'json', label: 'JSON 路径' },
  { value: 'regex', label: '正则（第 1 个捕获组）' },
  { value: 'header', label: '响应头' },
]
function extractPlaceholder(from: ExtractFrom): string {
  if (from === 'json') return '点号路径，如 data.items.0.id'
  if (from === 'regex') return '正则表达式，如 "token":"([^"]+)"'
  return '响应头名称，如 Set-Cookie'
}
function addExtract(): void {
  form.value.extracts.push({ var: '', from: 'json', expr: '' })
}

const sendBlocker = computed<string | null>(() => {
  if (ctx.blocker.value) return ctx.blocker.value
  if (!form.value.path.trim().startsWith('/')) return '路径必须以 / 开头'
  return null
})

async function send(): Promise<void> {
  const env = ctx.environment.value
  if (!env || sendBlocker.value || running.value) return
  if (!(await ctx.ensureProdConfirmed())) return
  const input = toInput(form.value)
  if (!input.name) input.name = '未命名接口'
  const r = await run({
    envId: env.id,
    ...(env.type === 'prod' ? { confirmProd: true } : {}),
    vars: ctx.vars.value,
    api: input,
  })
  updatedVars.value = r ? ctx.applyExtracted(r) : []
}
const updatedVars = ref<string[]>([])
const step = computed(() => result.value?.steps[0] ?? null)

function onKey(e: KeyboardEvent): void {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    void send()
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

async function copyText(text: string): Promise<boolean> {
  // 服务通常跑在内网的 http 地址上，navigator.clipboard 只在安全上下文可用，所以留一条旧路
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }
    document.body.removeChild(area)
    return ok
  }
}

async function copyCurl(): Promise<void> {
  const env = ctx.environment.value
  const text = buildCurl(toInput(form.value), env?.baseUrl ?? 'https://被测环境地址', env?.headers ?? {})
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
      <span v-if="dirty" class="unsaved">未保存</span>
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
        <el-input v-model="form.path" class="url-path" placeholder="/api/orders/{{orderId}}?page=1" />
      </div>
      <el-tooltip :content="sendBlocker ?? 'Ctrl + Enter'" placement="bottom">
        <span>
          <el-button type="primary" :icon="Position" :loading="running" :disabled="!!sendBlocker" @click="send">
            {{ running ? '发送中' : '发送' }}
          </el-button>
        </span>
      </el-tooltip>
      <el-button :loading="saving" :disabled="!dirty" @click="emit('save')">保存</el-button>
    </div>

    <el-tabs v-model="tab" class="req-tabs">
      <el-tab-pane name="params">
        <template #label>参数<span v-if="queryCount" class="tab-count">{{ queryCount }}</span></template>
        <KeyValueEditor
          :model-value="queryRows"
          key-placeholder="参数名"
          value-placeholder="值，可以用 {{变量名}}"
          add-text="添加参数"
          @update:model-value="onQueryRows"
        />
      </el-tab-pane>

      <el-tab-pane name="headers">
        <template #label>
          请求头<span v-if="headerCount + inheritedHeaders.length" class="tab-count">{{ headerCount + inheritedHeaders.length }}</span>
        </template>
        <div v-if="inheritedHeaders.length" class="inherited">
          <div class="inherited-title">
            继承自「{{ ctx.environment.value?.name }}」
          </div>
          <div v-for="h in inheritedHeaders" :key="h.name" class="inherited-row" :class="{ 'is-overridden': h.overridden }">
            <span class="inherited-key">{{ h.name }}</span>
            <span class="inherited-value mono">{{ h.value }}</span>
            <span v-if="h.overridden" class="inherited-note">已覆盖</span>
          </div>
        </div>
        <div v-if="inheritedHeaders.length" class="inherited-title own-title">接口</div>
        <KeyValueEditor
          v-model="form.headers"
          key-placeholder="请求头名称，如 Authorization"
          value-placeholder="值，可以用 {{变量名}}"
          add-text="添加请求头"
        />
      </el-tab-pane>

      <el-tab-pane name="body">
        <template #label>请求体<span v-if="form.body" class="tab-dot" /></template>
        <div class="body-tools">
          <el-button size="small" :disabled="!bodyIsJsonLike" @click="formatBody">格式化 JSON</el-button>
        </div>
        <el-input v-model="form.body" type="textarea" :rows="8" class="mono" placeholder='{"orderId": "{{orderId}}"}' />
      </el-tab-pane>

      <el-tab-pane name="expect" label="期望">
        <el-form label-width="130px" class="expect-form">
          <el-form-item label="期望状态码">
            <el-input-number v-model="form.expectStatus" :min="100" :max="599" :precision="0" controls-position="right" />
          </el-form-item>
          <el-form-item label="期望包含的文本">
            <el-input v-model="form.expectBodyContains" placeholder="留空表示不检查响应内容" />
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane name="extract">
        <template #label>变量提取<span v-if="extractCount" class="tab-count">{{ extractCount }}</span></template>
        <div class="row-list">
          <div v-for="(item, index) in form.extracts" :key="index" class="row-item">
            <el-input v-model="item.var" placeholder="变量名" style="width: 160px" class="mono" />
            <el-select v-model="item.from" style="width: 180px">
              <el-option v-for="s in EXTRACT_SOURCES" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
            <el-input v-model="item.expr" class="grow mono" :placeholder="extractPlaceholder(item.from)" />
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
        <DebugVarsEditor />
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
      <DebugStepPanel v-else-if="step" :step="step" />
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
  flex-shrink: 0;
  max-width: 48%;
  border-right: 1px solid var(--hairline);
}
.url-path {
  flex: 1;
  min-width: 0;
  --el-input-border-color: transparent;
  --el-input-hover-border-color: transparent;
  --el-input-focus-border-color: transparent;
}
.url-path :deep(.el-input__wrapper) {
  box-shadow: none !important;
}
.url-path :deep(.el-input__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}
.request-bar .el-button + .el-button {
  margin-left: 0;
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
.body-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.body-hint {
  width: auto;
  margin: 0;
}
.expect-form {
  max-width: 640px;
}

.inherited {
  margin-bottom: 12px;
  padding: 8px 10px;
  border: 1px dashed var(--hairline);
  border-radius: 6px;
  background: #fafbfc;
}
.inherited-title {
  margin-bottom: 6px;
  color: var(--el-text-color-regular);
  font-size: 12px;
}
.own-title {
  margin-bottom: 8px;
}
.inherited-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 3px 0;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.inherited-key {
  width: 38%;
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.inherited-value {
  flex: 1;
  min-width: 0;
  word-break: break-all;
}
.inherited-row.is-overridden .inherited-key,
.inherited-row.is-overridden .inherited-value {
  color: var(--ink-muted);
  text-decoration: line-through;
}
.inherited-note {
  flex-shrink: 0;
  color: var(--el-color-warning);
  font-size: 12px;
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
