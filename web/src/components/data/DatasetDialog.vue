<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Download, Upload } from '@element-plus/icons-vue'
import { ApiError, datasetsApi, type DatasetData, type DatasetDetail, type DatasetInput, type DatasetPreview } from '../../api'
import { errorMessage, showError } from '../../utils/feedback'
import { formatBytes } from '../../utils/format'
import { oversizeMessage, readFileBase64 } from '../../utils/test-data'
import CsvPreview from './CsvPreview.vue'

const visible = defineModel<boolean>({ required: true })
const props = defineProps<{ datasetId: number | null }>()
const emit = defineEmits<{ saved: [] }>()

/** 超过这么多行就不拿 CSV 文本来编辑，只能上传整体替换 */
const TEXT_EDIT_MAX_ROWS = 2000

const name = ref('')
const note = ref('')
const detail = ref<DatasetDetail | null>(null)
const loading = ref(false)
const textLoading = ref(false)
/** null：可以编辑文本；否则是不能编辑的原因 */
const textBlocked = ref<string | null>(null)
const text = ref('')
const originalText = ref('')
const upload = ref<{ name: string; size: number; base64: string } | null>(null)
const preview = ref<DatasetPreview | null>(null)
const previewError = ref<{ message: string; details: string[] } | null>(null)
const previewing = ref(false)
const saving = ref(false)
const fileInput = ref<HTMLInputElement>()

const isNew = computed(() => props.datasetId === null)
const textChanged = computed(() => textBlocked.value === null && text.value !== originalText.value)

/** 文本框里的换行会被浏览器规整成 \n，原文也按这个规整，否则没改也算改了 */
const normalize = (csv: string) => csv.replace(/\r\n?/g, '\n')

function previewFromDetail(): DatasetPreview | null {
  const d = detail.value
  return d ? { columns: d.columns, rowCount: d.rowCount, previewRows: d.previewRows, source: d.source } : null
}

let seq = 0
let timer: number | undefined

async function runPreview(data: DatasetData): Promise<void> {
  const mine = (seq += 1)
  previewing.value = true
  try {
    const result = await datasetsApi.preview(data)
    if (mine !== seq) return
    preview.value = result
    previewError.value = null
  } catch (e) {
    if (mine !== seq) return
    preview.value = null
    previewError.value = { message: errorMessage(e), details: e instanceof ApiError ? e.details : [] }
  } finally {
    if (mine === seq) previewing.value = false
  }
}

/** 数据区当前内容对应的预览：上传的文件 > 改过的文本 > 已保存的数据 */
function refreshPreview(): void {
  window.clearTimeout(timer)
  if (upload.value) {
    void runPreview({ contentBase64: upload.value.base64, fileName: upload.value.name })
    return
  }
  seq += 1
  previewing.value = false
  previewError.value = null
  if (!textChanged.value) {
    preview.value = previewFromDetail()
    return
  }
  if (!text.value.trim()) {
    preview.value = null
    return
  }
  previewing.value = true
  timer = window.setTimeout(() => void runPreview({ csv: text.value }), 400)
}
watch(text, refreshPreview)
onBeforeUnmount(() => window.clearTimeout(timer))

function reset(): void {
  window.clearTimeout(timer)
  seq += 1
  name.value = ''
  note.value = ''
  detail.value = null
  textBlocked.value = null
  text.value = ''
  originalText.value = ''
  upload.value = null
  preview.value = null
  previewError.value = null
  previewing.value = false
}

async function loadExisting(id: number): Promise<void> {
  loading.value = true
  try {
    const d = await datasetsApi.get(id)
    if (props.datasetId !== id || !visible.value) return
    detail.value = d
    name.value = d.name
    note.value = d.note ?? ''
    preview.value = previewFromDetail()
    if (d.rowCount > TEXT_EDIT_MAX_ROWS) {
      textBlocked.value = `超过 ${TEXT_EDIT_MAX_ROWS} 行，用上传整体替换`
      return
    }
    textLoading.value = true
    try {
      const csv = normalize(await datasetsApi.csvText(id))
      if (props.datasetId !== id || !visible.value) return
      originalText.value = csv
      text.value = csv
    } catch (e) {
      textBlocked.value = `CSV 文本加载失败：${errorMessage(e)}`
    } finally {
      textLoading.value = false
    }
  } catch (e) {
    showError(e, '加载数据集失败')
    visible.value = false
  } finally {
    loading.value = false
  }
}

watch(visible, (open) => {
  if (!open) return
  reset()
  if (props.datasetId !== null) void loadExisting(props.datasetId)
})

function pickFile(): void {
  fileInput.value?.click()
}
async function onFileChosen(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const tooBig = oversizeMessage(file)
  if (tooBig) {
    ElMessage.error(tooBig)
    return
  }
  try {
    upload.value = { name: file.name, size: file.size, base64: await readFileBase64(file) }
  } catch (err) {
    showError(err, '读取文件失败')
    return
  }
  refreshPreview()
}
function clearUpload(): void {
  upload.value = null
  refreshPreview()
}

async function save(): Promise<void> {
  const trimmed = name.value.trim()
  if (!trimmed) {
    ElMessage.warning('请填写名称')
    return
  }
  let data: DatasetData | null = null
  if (upload.value) data = { contentBase64: upload.value.base64, fileName: upload.value.name }
  else if (textChanged.value && (!isNew.value || text.value.trim())) data = { csv: text.value }
  if (isNew.value && !data) {
    ElMessage.warning('请上传 CSV 或填写数据')
    return
  }
  const input: DatasetInput = data ? { name: trimmed, note: note.value, ...data } : { name: trimmed, note: note.value }
  saving.value = true
  try {
    if (props.datasetId === null) await datasetsApi.create(input)
    else await datasetsApi.update(props.datasetId, input)
    ElMessage.success('已保存')
    visible.value = false
    emit('saved')
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isNew ? '新建数据集' : '编辑数据集'"
    width="980px"
    top="5vh"
    :close-on-click-modal="false"
  >
    <div v-loading="loading">
      <el-form label-width="60px" class="ds-form">
        <el-form-item label="名称" required>
          <el-input v-model="name" maxlength="100" placeholder="例如：账号池" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="note" />
        </el-form-item>
      </el-form>

      <div class="ds-tools">
        <el-button :icon="Upload" @click="pickFile">上传 CSV</el-button>
        <el-button v-if="!isNew && datasetId !== null" :icon="Download" tag="a" :href="datasetsApi.csvUrl(datasetId, true)">
          下载 CSV
        </el-button>
        <span v-if="upload" class="ds-upload">
          <span class="mono">{{ upload.name }}</span>
          <span class="muted">{{ formatBytes(upload.size) }}</span>
          <el-button :icon="Close" circle text size="small" title="撤销上传" @click="clearUpload" />
        </span>
        <span v-else-if="textBlocked" class="ds-blocked">{{ textBlocked }}</span>
        <input ref="fileInput" type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" hidden @change="onFileChosen" />
      </div>

      <el-input
        v-if="!upload && textBlocked === null"
        v-model="text"
        v-loading="textLoading"
        type="textarea"
        :rows="10"
        class="ds-text"
        spellcheck="false"
        :placeholder="'username,password\nalice,123456'"
      />

      <div class="ds-preview">
        <el-alert v-if="previewError" type="error" :closable="false" show-icon :title="previewError.message">
          <ul v-if="previewError.details.length" class="ds-errors">
            <li v-for="(item, i) in previewError.details" :key="i">{{ item }}</li>
          </ul>
        </el-alert>
        <div v-else-if="preview" v-loading="previewing">
          <CsvPreview :columns="preview.columns" :rows="preview.previewRows" :row-count="preview.rowCount" :source="preview.source" />
        </div>
        <div v-else-if="previewing" v-loading="true" class="ds-preview-pending" />
      </div>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="loading" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.ds-form {
  max-width: 640px;
}
.ds-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.ds-tools .el-button + .el-button {
  margin-left: 0;
}
.ds-upload {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 2px 4px 2px 10px;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  background: #fafbfc;
  font-size: 13px;
}
.ds-blocked {
  color: var(--el-color-warning-dark-2);
  font-size: 13px;
}
.ds-text :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
  white-space: pre;
  overflow-wrap: normal;
}
.ds-preview {
  margin-top: 12px;
}
.ds-preview-pending {
  height: 60px;
}
.ds-errors {
  margin: 4px 0 0;
  padding-left: 18px;
  line-height: 1.8;
}
</style>
