<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { filesApi, type FileAsset } from '../../api'
import { useResourceList } from '../../composables/useResourceList'
import { showError } from '../../utils/feedback'
import { formatBytes, formatTime } from '../../utils/format'
import { oversizeMessage, readFileBase64 } from '../../utils/test-data'

const { items, loading, load, remove } = useResourceList(filesApi, '文件')

const uploadInput = ref<HTMLInputElement>()
const replaceInput = ref<HTMLInputElement>()
const uploading = ref(false)
const replacing = ref<FileAsset | null>(null)

function pickUpload(): void {
  uploadInput.value?.click()
}
async function onUpload(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const chosen = [...(input.files ?? [])]
  input.value = ''
  if (!chosen.length) return
  uploading.value = true
  let done = 0
  try {
    for (const file of chosen) {
      const tooBig = oversizeMessage(file)
      if (tooBig) {
        ElMessage.error(tooBig)
        continue
      }
      try {
        await filesApi.create({ name: file.name, contentType: file.type, note: '', contentBase64: await readFileBase64(file) })
        done += 1
      } catch (err) {
        showError(err, `上传「${file.name}」失败`)
      }
    }
  } finally {
    uploading.value = false
  }
  if (done) {
    ElMessage.success(done > 1 ? `已上传 ${done} 个文件` : '已上传')
    await load()
  }
}

function pickReplace(row: FileAsset): void {
  replacing.value = row
  replaceInput.value?.click()
}
async function onReplace(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const row = replacing.value
  if (!file || !row) return
  const tooBig = oversizeMessage(file)
  if (tooBig) {
    ElMessage.error(tooBig)
    return
  }
  try {
    const contentBase64 = await readFileBase64(file)
    await filesApi.update(row.id, { name: row.name, contentType: row.contentType, note: row.note ?? '', contentBase64 })
    ElMessage.success(`已替换「${row.name}」的内容`)
    await load()
  } catch (err) {
    showError(err, '替换失败')
  }
}

const editVisible = ref(false)
const editing = ref<FileAsset | null>(null)
const editForm = reactive({ name: '', contentType: '', note: '' })
const savingEdit = ref(false)
function openEdit(row: FileAsset): void {
  editing.value = row
  Object.assign(editForm, { name: row.name, contentType: row.contentType, note: row.note ?? '' })
  editVisible.value = true
}
const BAD_NAME = /[/\\\u0000-\u001f\u007f]/
async function saveEdit(): Promise<void> {
  const row = editing.value
  if (!row) return
  const name = editForm.name.trim()
  if (!name) {
    ElMessage.warning('请填写文件名')
    return
  }
  if (name.length > 200 || BAD_NAME.test(name)) {
    ElMessage.warning('文件名不超过 200 个字符，不能包含 / \\ 和控制字符')
    return
  }
  savingEdit.value = true
  try {
    await filesApi.update(row.id, { name, contentType: editForm.contentType.trim(), note: editForm.note })
    ElMessage.success('已保存')
    editVisible.value = false
    await load()
  } catch (err) {
    showError(err, '保存失败')
  } finally {
    savingEdit.value = false
  }
}

defineExpose({ pickUpload, uploading })
</script>

<template>
  <el-table v-loading="loading || uploading" :data="items" empty-text="暂无文件">
    <el-table-column label="文件名" min-width="200">
      <template #default="{ row }">
        <span class="mono">{{ (row as FileAsset).name }}</span>
        <div v-if="(row as FileAsset).note" class="muted file-note">{{ (row as FileAsset).note }}</div>
      </template>
    </el-table-column>
    <el-table-column label="类型" min-width="160">
      <template #default="{ row }">
        <span class="mono">{{ (row as FileAsset).contentType }}</span>
      </template>
    </el-table-column>
    <el-table-column label="大小" width="110" align="right">
      <template #default="{ row }">
        <span class="num">{{ formatBytes((row as FileAsset).size) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="引用的接口" min-width="180">
      <template #default="{ row }">
        <div v-if="(row as FileAsset).usedBy?.length" class="tag-line">
          <el-tag v-for="u in (row as FileAsset).usedBy" :key="u.apiId" size="small" effect="plain" disable-transitions>
            {{ u.apiName }}
          </el-tag>
        </div>
        <span v-else class="muted">—</span>
      </template>
    </el-table-column>
    <el-table-column label="更新时间" width="170">
      <template #default="{ row }">
        <span class="num">{{ formatTime((row as FileAsset).updatedAt) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="250" fixed="right">
      <template #default="{ row }">
        <el-button link type="primary" tag="a" :href="filesApi.contentUrl((row as FileAsset).id, true)">下载</el-button>
        <el-button link type="primary" @click="pickReplace(row as FileAsset)">替换内容</el-button>
        <el-button link type="primary" @click="openEdit(row as FileAsset)">编辑</el-button>
        <el-button link type="danger" @click="remove(row as FileAsset)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <input ref="uploadInput" type="file" multiple hidden @change="onUpload" />
  <input ref="replaceInput" type="file" hidden @change="onReplace" />

  <el-dialog v-model="editVisible" title="编辑文件" width="520px" :close-on-click-modal="false">
    <el-form label-width="70px">
      <el-form-item label="文件名" required>
        <el-input v-model="editForm.name" maxlength="200" class="mono" />
      </el-form-item>
      <el-form-item label="类型">
        <el-input v-model="editForm.contentType" class="mono" placeholder="application/octet-stream" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="editForm.note" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editVisible = false">取消</el-button>
      <el-button type="primary" :loading="savingEdit" @click="saveEdit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.file-note {
  font-size: 12px;
}
.tag-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
