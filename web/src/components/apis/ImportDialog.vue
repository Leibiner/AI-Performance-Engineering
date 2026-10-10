<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Close, Folder as FolderIcon, InfoFilled, Upload, WarningFilled } from '@element-plus/icons-vue'
import type { ElTree } from 'element-plus'
import { ApiError, importsApi, type ImportApiDraft, type ImportPreview, type ImportResult, type ImportSource } from '../../api'
import { useDebugContext } from '../../composables/useDebugContext'
import { showError } from '../../utils/feedback'
import type { FolderOption } from '../../utils/folders'
import { formatBytes } from '../../utils/format'
import { METHOD_COLOR } from '../../utils/method'
import EnvTypeTag from '../EnvTypeTag.vue'

const MAX_BYTES = 10 * 1024 * 1024

const visible = defineModel<boolean>({ required: true })
defineProps<{ folderOptions: FolderOption[] }>()
const emit = defineEmits<{ imported: [result: ImportResult, title: string] }>()

const ctx = useDebugContext()

const text = ref('')
const url = ref('')
const file = ref<{ name: string; size: number; text: string } | null>(null)
const fileInput = ref<HTMLInputElement>()
const preview = ref<ImportPreview | null>(null)
const previewError = ref<ApiError | null>(null)
const previewing = ref(false)
const targetFolderId = ref<number | null>(null)
const checked = ref<string[]>([])
const importing = ref(false)
const treeRef = ref<InstanceType<typeof ElTree>>()

watch(visible, (open) => {
  if (!open) return
  text.value = ''
  url.value = ''
  file.value = null
  preview.value = null
  previewError.value = null
  targetFolderId.value = null
  void ctx.loadEnvironments()
})

let seq = 0
async function runPreview(source: ImportSource): Promise<void> {
  const mine = ++seq
  previewing.value = true
  try {
    const result = await importsApi.preview(source)
    if (mine !== seq) return
    preview.value = result
    previewError.value = null
    checked.value = result.apis.filter((a) => !a.problems.length && !a.duplicateOf).map((a) => a.key)
    await nextTick()
    treeRef.value?.setCheckedKeys(checked.value)
  } catch (e) {
    if (mine !== seq) return
    preview.value = null
    previewError.value = e instanceof ApiError ? e : new ApiError(0, 'CLIENT', e instanceof Error ? e.message : String(e))
  } finally {
    if (mine === seq) previewing.value = false
  }
}
function clearPreview(): void {
  seq += 1
  previewing.value = false
  preview.value = null
  previewError.value = null
}

let timer: ReturnType<typeof setTimeout> | undefined
watch(text, (value) => {
  clearTimeout(timer)
  if (file.value) return
  if (!value.trim()) {
    clearPreview()
    return
  }
  timer = setTimeout(() => void runPreview({ text: value }), 600)
})

async function onFileChosen(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const chosen = input.files?.[0]
  input.value = ''
  if (!chosen) return
  if (chosen.size > MAX_BYTES) {
    showError(new Error(`文件超过 ${formatBytes(MAX_BYTES)}`), '读取文件失败')
    return
  }
  try {
    file.value = { name: chosen.name, size: chosen.size, text: await chosen.text() }
  } catch (err) {
    showError(err, '读取文件失败')
    return
  }
  clearTimeout(timer)
  void runPreview({ text: file.value.text })
}
function clearFile(): void {
  file.value = null
  if (text.value.trim()) void runPreview({ text: text.value })
  else clearPreview()
}
function fetchUrl(): void {
  const value = url.value.trim()
  if (!value) return
  file.value = null
  clearTimeout(timer)
  void runPreview({ url: value })
}

interface Node {
  key: string
  kind: 'folder' | 'api'
  label: string
  disabled?: boolean
  draft?: ImportApiDraft
  children?: Node[]
}
const treeData = computed<Node[]>(() => {
  const p = preview.value
  if (!p) return []
  const folders = new Map<string, Node>()
  const roots: Node[] = []
  for (const f of p.folders) {
    const node: Node = { key: f.key, kind: 'folder', label: f.name, children: [] }
    folders.set(f.key, node)
    const parent = f.parentKey !== null ? folders.get(f.parentKey) : undefined
    ;(parent ? parent.children! : roots).push(node)
  }
  for (const a of p.apis) {
    const node: Node = { key: a.key, kind: 'api', label: a.api.name, draft: a, disabled: a.problems.length > 0 }
    const parent = a.folderKey !== null ? folders.get(a.folderKey) : undefined
    ;(parent ? parent.children! : roots).push(node)
  }
  return roots
})
const apiKeys = computed(() => new Set(preview.value?.apis.map((a) => a.key) ?? []))
const selectedCount = computed(() => checked.value.filter((k) => apiKeys.value.has(k)).length)
function onCheck(): void {
  checked.value = (treeRef.value?.getCheckedKeys(true) ?? []).map(String)
}

/** 文档里的地址有没有对应的被测环境（按协议 + 主机比较） */
function originOf(value: string): string | null {
  try {
    return new URL(value).origin
  } catch {
    return null
  }
}
const baseUrls = computed(() =>
  (preview.value?.baseUrls ?? []).map((value) => {
    const origin = originOf(value)
    const env = origin ? ctx.environments.value.find((e) => originOf(e.baseUrl) === origin) : undefined
    return { value, env }
  }),
)

async function submit(): Promise<void> {
  const p = preview.value
  if (!p || selectedCount.value === 0) return
  const picked = p.apis.filter((a) => checked.value.includes(a.key))
  // 只建装着选中接口的文件夹（和它们的上级）
  const parents = new Map(p.folders.map((f) => [f.key, f.parentKey]))
  const needed = new Set<string>()
  for (const a of picked) {
    let key = a.folderKey
    while (key !== null && !needed.has(key)) {
      needed.add(key)
      key = parents.get(key) ?? null
    }
  }
  importing.value = true
  try {
    const result = await importsApi.create({
      folderId: targetFolderId.value,
      folders: p.folders.filter((f) => needed.has(f.key)),
      apis: picked.map((a) => ({ ...a.api, folderKey: a.folderKey })),
    })
    emit('imported', result, p.title)
    visible.value = false
  } catch (e) {
    showError(e, '导入失败')
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="从 OpenAPI / Postman 导入" width="900px" top="6vh" :close-on-click-modal="false">
    <div class="imp-source">
      <el-button :icon="Upload" @click="fileInput?.click()">选择文件</el-button>
      <input ref="fileInput" type="file" accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml" hidden @change="onFileChosen" />
      <el-input v-model="url" class="imp-url" placeholder="文档地址，例如 http://host/openapi.json" clearable @keyup.enter="fetchUrl">
        <template #append>
          <el-button :disabled="!url.trim()" @click="fetchUrl">获取</el-button>
        </template>
      </el-input>
    </div>
    <div v-if="file" class="imp-file">
      <span class="mono">{{ file.name }}</span>
      <span class="muted">{{ formatBytes(file.size) }}</span>
      <el-button :icon="Close" circle text size="small" title="撤销" @click="clearFile" />
    </div>
    <el-input
      v-else
      v-model="text"
      type="textarea"
      :rows="5"
      class="imp-text"
      spellcheck="false"
      placeholder="或粘贴 OpenAPI 3 / Swagger 2.0（JSON、YAML）、Postman Collection v2（JSON）"
    />

    <div v-loading="previewing" class="imp-result">
      <el-alert v-if="previewError" type="error" :closable="false" show-icon :title="previewError.message">
        <ul v-if="previewError.details.length" class="imp-list">
          <li v-for="(item, i) in previewError.details" :key="i">{{ item }}</li>
        </ul>
      </el-alert>

      <template v-else-if="preview">
        <div class="imp-summary">
          <strong>{{ preview.title }}</strong>
          <el-tag size="small" type="info" effect="plain">{{ preview.formatLabel }}</el-tag>
          <span class="muted">
            {{ preview.apis.length }} 个接口<template v-if="preview.skipped.length">，跳过 {{ preview.skipped.length }} 个</template>
          </span>
        </div>
        <div v-for="b in baseUrls" :key="b.value" class="imp-base">
          <span class="muted">原地址</span>
          <span class="mono">{{ b.value }}</span>
          <span v-if="b.env" class="imp-env"><EnvTypeTag :type="b.env.type" />{{ b.env.name }}</span>
        </div>

        <el-tree
          v-if="preview.apis.length"
          ref="treeRef"
          :data="treeData"
          node-key="key"
          show-checkbox
          default-expand-all
          :expand-on-click-node="false"
          :default-checked-keys="checked"
          :indent="14"
          class="imp-tree"
          @check="onCheck"
        >
          <template #default="{ data: node }">
            <div class="imp-row">
              <template v-if="node.kind === 'folder'">
                <el-icon class="imp-folder-icon"><FolderIcon /></el-icon>
                <span class="imp-name is-folder">{{ node.label }}</span>
              </template>
              <template v-else>
                <span class="imp-method" :style="{ color: METHOD_COLOR[node.draft.api.method as keyof typeof METHOD_COLOR] }">{{ node.draft.api.method }}</span>
                <span class="imp-name">{{ node.label }}</span>
                <span class="imp-path mono" :title="node.draft.api.path">{{ node.draft.api.path }}</span>
                <el-tooltip v-if="node.draft.duplicateOf" placement="top" :content="`和已有的接口「${node.draft.duplicateOf.name}」方法、路径相同`">
                  <el-tag size="small" type="warning" effect="plain">已存在</el-tag>
                </el-tooltip>
                <el-tooltip v-if="node.draft.problems.length" placement="top">
                  <template #content><div v-for="(p, i) in node.draft.problems" :key="i">{{ p }}</div></template>
                  <el-tag size="small" type="danger" effect="plain">不能导入</el-tag>
                </el-tooltip>
                <el-tooltip v-if="node.draft.notes.length" placement="top">
                  <template #content><div v-for="(n, i) in node.draft.notes" :key="i">{{ n }}</div></template>
                  <el-icon class="imp-note"><InfoFilled /></el-icon>
                </el-tooltip>
              </template>
            </div>
          </template>
        </el-tree>
        <div v-else class="imp-empty muted">文档里没有可导入的接口</div>

        <ul v-if="preview.skipped.length || preview.warnings.length" class="imp-list imp-skipped">
          <li v-for="(w, i) in preview.warnings" :key="`w${i}`">
            <el-icon class="imp-warn"><WarningFilled /></el-icon>{{ w }}
          </li>
          <li v-for="(s, i) in preview.skipped" :key="`s${i}`">跳过「{{ s.name }}」：{{ s.reason }}</li>
        </ul>
      </template>
    </div>

    <template #footer>
      <div class="imp-footer">
        <span class="imp-target">
          <span class="muted">导入到</span>
          <el-tree-select
            v-model="targetFolderId"
            :data="folderOptions"
            check-strictly
            clearable
            :render-after-expand="false"
            placeholder="根目录"
            class="imp-target-select"
          />
        </span>
        <span>
          <el-button @click="visible = false">取消</el-button>
          <el-button type="primary" :loading="importing" :disabled="!preview || selectedCount === 0" @click="submit">
            导入 {{ selectedCount }} 个接口
          </el-button>
        </span>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.imp-source {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}
.imp-url {
  flex: 1;
  min-width: 0;
}
.imp-file {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 2px 4px 2px 10px;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  background: #fafbfc;
  font-size: 13px;
}
.imp-text :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
}
.imp-result {
  min-height: 40px;
  margin-top: 12px;
}
.imp-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.imp-base {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 13px;
}
.imp-env {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.imp-tree {
  --el-tree-node-content-height: 30px;
  max-height: 46vh;
  margin-top: 8px;
  padding: 4px;
  overflow: auto;
  border: 1px solid var(--hairline);
  border-radius: 8px;
}
.imp-row {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: 8px;
  padding-right: 6px;
}
.imp-folder-icon {
  flex-shrink: 0;
  color: #d9a441;
}
.imp-method {
  flex-shrink: 0;
  width: 46px;
  font-size: 11px;
  font-weight: 700;
}
.imp-name {
  flex-shrink: 0;
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
}
.imp-name.is-folder {
  max-width: none;
  font-weight: 600;
}
.imp-path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--ink-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.imp-note {
  flex-shrink: 0;
  color: var(--el-color-info);
}
.imp-empty {
  padding: 20px 0;
  text-align: center;
}
.imp-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
}
.imp-skipped {
  max-height: 120px;
  overflow: auto;
  padding-left: 0;
  color: var(--ink-muted);
  list-style: none;
}
.imp-warn {
  margin-right: 4px;
  color: var(--el-color-warning);
  vertical-align: -2px;
}
.imp-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.imp-target {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.imp-target-select {
  width: 220px;
}
</style>
