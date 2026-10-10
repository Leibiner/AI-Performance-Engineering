<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Plus, Upload } from '@element-plus/icons-vue'
import { useFileList } from '../../composables/useFileList'
import { isBlankRow, type ApiForm, type BodyMode, type FormRow } from '../../utils/api-form'
import { tryPrettyJson } from '../../utils/debug'
import { formatBytes } from '../../utils/format'
import { brokenLabel } from '../../utils/references'
import VarInput from '../VarInput.vue'

const form = defineModel<ApiForm>({ required: true })
const props = defineProps<{
  vars: Record<string, string>
  producers: Record<string, string[]>
  hints: Record<string, string>
  envHeaders: Record<string, string>
}>()

const MODES: { value: BodyMode; label: string }[] = [
  { value: 'none', label: 'none' },
  { value: 'multipart', label: 'form-data' },
  { value: 'form', label: 'x-www-form-urlencoded' },
  { value: 'raw', label: 'raw' },
]

const isForm = computed(() => form.value.bodyMode === 'form' || form.value.bodyMode === 'multipart')
const bodyIsJsonLike = computed(() => /^\s*[[{]/.test(form.value.body))

function formatBody(): void {
  const pretty = tryPrettyJson(form.value.body)
  if (pretty) form.value.body = pretty
  else ElMessage.warning('请求体不是合法的 JSON，没有改动')
}

const contentTypeReplaced = computed(
  () =>
    form.value.bodyMode === 'multipart' &&
    (form.value.headers.some((r) => r.key.trim().toLowerCase() === 'content-type') ||
      Object.keys(props.envHeaders).some((k) => k.toLowerCase() === 'content-type')),
)
const fileInUrlencoded = computed(
  () => form.value.bodyMode === 'form' && form.value.form.some((r) => r.type === 'file' && !isBlankRow(r)),
)

function addRow(): void {
  form.value.form.push({ name: '', type: 'text', value: '', fileId: null })
}

const { files, loaded: filesLoaded, refresh: refreshFiles, upload } = useFileList()
onMounted(() => {
  void refreshFiles(true)
})
function onFileListOpen(open: boolean): void {
  if (open) void refreshFiles()
}
function missingFileLabel(id: number): string {
  return filesLoaded.value ? brokenLabel('file', id) : `文件 #${id}`
}

const uploadInput = ref<HTMLInputElement>()
const uploadRow = ref<FormRow | null>(null)
const uploading = ref<FormRow | null>(null)
function pickUpload(row: FormRow): void {
  uploadRow.value = row
  uploadInput.value?.click()
}
async function onUploadChosen(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const row = uploadRow.value
  if (!file || !row) return
  uploading.value = row
  try {
    const created = await upload(file)
    if (created) {
      row.fileId = created.id
      ElMessage.success(`已上传「${created.name}」`)
    }
  } finally {
    uploading.value = null
  }
}
</script>

<template>
  <div class="body-editor">
    <div class="body-modes">
      <el-radio-group v-model="form.bodyMode" size="small">
        <el-radio v-for="m in MODES" :key="m.value" :value="m.value">{{ m.label }}</el-radio>
      </el-radio-group>
      <el-button v-if="form.bodyMode === 'raw'" size="small" :disabled="!bodyIsJsonLike" class="body-format" @click="formatBody">
        格式化 JSON
      </el-button>
    </div>

    <VarInput
      v-if="form.bodyMode === 'raw'"
      v-model="form.body"
      multiline
      :rows="8"
      :vars="vars"
      :producers="producers"
      :hints="hints"
      placeholder='{"orderId": "{{orderId}}"}'
    />

    <template v-else-if="isForm">
      <el-alert
        v-if="contentTypeReplaced"
        type="warning"
        :closable="false"
        show-icon
        class="body-alert"
        title="Content-Type 会被替换为 multipart/form-data; boundary=…"
      />
      <el-alert
        v-if="fileInUrlencoded"
        type="error"
        :closable="false"
        show-icon
        class="body-alert"
        title="x-www-form-urlencoded 不能包含文件项"
      />
      <div class="row-list">
        <div v-for="(row, index) in form.form" :key="index" class="row-item form-row">
          <div class="form-name">
            <VarInput v-model="row.name" :vars="vars" :producers="producers" :hints="hints" placeholder="名称" />
          </div>
          <el-select v-if="form.bodyMode === 'multipart' || row.type === 'file'" v-model="row.type" class="form-type">
            <el-option value="text" label="文本" />
            <el-option value="file" label="文件" :disabled="form.bodyMode === 'form'" />
          </el-select>
          <div class="grow">
            <div v-if="row.type === 'file'" class="file-pick">
              <el-select
                v-model="row.fileId"
                filterable
                placeholder="选择文件"
                no-data-text="还没有上传文件"
                class="file-select"
                :disabled="form.bodyMode === 'form'"
                @visible-change="onFileListOpen"
              >
                <el-option v-for="f in files" :key="f.id" :label="f.name" :value="f.id">
                  <span class="file-option">
                    <span class="file-option-name">{{ f.name }}</span>
                    <span class="file-option-meta">{{ f.contentType }} · {{ formatBytes(f.size) }}</span>
                  </span>
                </el-option>
                <el-option
                  v-if="row.fileId !== null && !files.some((f) => f.id === row.fileId)"
                  :value="row.fileId"
                  :label="missingFileLabel(row.fileId)"
                />
              </el-select>
              <el-button
                :icon="Upload"
                :loading="uploading === row"
                :disabled="form.bodyMode === 'form'"
                title="上传新文件"
                @click="pickUpload(row)"
              />
            </div>
            <VarInput v-else v-model="row.value" :vars="vars" :producers="producers" :hints="hints" placeholder="值" />
          </div>
          <el-button :icon="Delete" circle text title="删除这一项" @click="form.form.splice(index, 1)" />
        </div>
        <el-button :icon="Plus" size="small" @click="addRow">添加</el-button>
      </div>
      <input ref="uploadInput" type="file" hidden @change="onUploadChosen" />
    </template>
  </div>
</template>

<style scoped>
.body-modes {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.body-format {
  margin-left: auto;
}
.body-alert {
  margin-bottom: 8px;
}
.form-name {
  width: 30%;
  flex-shrink: 0;
}
.form-type {
  width: 88px;
  flex-shrink: 0;
}
.file-pick {
  display: flex;
  gap: 6px;
}
.file-select {
  flex: 1;
  min-width: 0;
}
.file-pick .el-button + .el-button {
  margin-left: 0;
}
.file-option {
  display: flex;
  align-items: center;
  gap: 12px;
}
.file-option-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-option-meta {
  flex-shrink: 0;
  color: var(--ink-muted);
  font-size: 12px;
}
</style>
