<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apisApi, foldersApi, type ApiDef, type Folder } from '../api'
import { useResourceList } from '../composables/useResourceList'
import { confirmAction, showError } from '../utils/feedback'
import { emptyForm, fromApi, snapshot, toInput, type ApiForm } from '../utils/api-form'
import type { CurlImport } from '../utils/curl'
import { buildFolderTree, folderOptions, folderPath } from '../utils/folders'
import { useApiIndex } from '../composables/useApiIndex'
import PageHeader from '../components/PageHeader.vue'
import ApiList from '../components/apis/ApiList.vue'
import ApiEditor from '../components/apis/ApiEditor.vue'
import CurlImportDialog from '../components/apis/CurlImportDialog.vue'
import DebugEnvBar from '../components/debug/DebugEnvBar.vue'

const { items, loading, load, remove } = useResourceList(apisApi, '接口')

const folders = ref<Folder[]>([])
async function loadFolders(): Promise<void> {
  try {
    folders.value = await foldersApi.list()
  } catch (e) {
    showError(e, '加载文件夹失败')
  }
}
onMounted(loadFolders)
const folderTree = computed(() => buildFolderTree(folders.value, items.value))
const folderSelectOptions = computed(() => folderOptions(folderTree.value.roots))
const apiIndex = useApiIndex()
const producers = apiIndex.producers
watch(items, () => void apiIndex.refresh())

async function promptName(title: string, initial = ''): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt('', title, {
      inputValue: initial,
      inputPlaceholder: '文件夹名称，例如：订单系统、下单模块',
      inputValidator: (v: string) => (v.trim() ? true : '请输入名称'),
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
    return value.trim()
  } catch {
    return null
  }
}
async function createFolder(parentId: number | null): Promise<void> {
  const where = parentId === null ? '新建顶层文件夹' : `在「${folderPath(folders.value, parentId)}」下新建文件夹`
  const name = await promptName(where)
  if (!name) return
  try {
    await foldersApi.create({ name, parentId, note: '' })
    await loadFolders()
    ElMessage.success(`已新建文件夹「${name}」`)
  } catch (e) {
    showError(e, '新建文件夹失败')
  }
}
async function renameFolder(folder: Folder): Promise<void> {
  const name = await promptName('重命名文件夹', folder.name)
  if (!name || name === folder.name) return
  try {
    await foldersApi.update(folder.id, { ...folder, name })
    await loadFolders()
  } catch (e) {
    showError(e, '重命名失败')
  }
}
async function deleteFolder(folder: Folder): Promise<void> {
  const ok = await confirmAction(`确定删除文件夹「${folder.name}」吗？只有空文件夹能删除。`, '删除文件夹', true)
  if (!ok) return
  try {
    await foldersApi.remove(folder.id)
    await loadFolders()
    ElMessage.success('已删除')
  } catch (e) {
    showError(e, '删除失败')
  }
}

const selectedId = ref<number | null>(null)
const form = ref<ApiForm | null>(null)
const baseline = ref('')
const saving = ref(false)
const importVisible = ref(false)

const isNew = computed(() => form.value !== null && selectedId.value === null)
const dirty = computed(() => form.value !== null && snapshot(form.value) !== baseline.value)
/** 正在新建时，新接口在树里的位置（跟着表单里的所属文件夹走） */
const draftFolderId = computed<number | null | undefined>(() => (isNew.value ? (form.value?.folderId ?? null) : undefined))

// 列表第一次加载完成时自动打开第一个，页面打开就有东西可看
watch(items, (list) => {
  if (form.value === null && selectedId.value === null && list.length > 0) open(list[0])
})

function open(api: ApiDef): void {
  selectedId.value = api.id
  form.value = fromApi(api)
  baseline.value = snapshot(form.value)
}

async function guard(): Promise<boolean> {
  if (!dirty.value) return true
  return confirmAction('当前接口有未保存的修改，放弃这些修改吗？', '未保存的修改', true)
}

async function select(api: ApiDef): Promise<void> {
  if (api.id === selectedId.value) return
  if (!(await guard())) return
  open(api)
}

async function create(folderId: number | null): Promise<void> {
  if (!(await guard())) return
  selectedId.value = null
  form.value = emptyForm(folderId)
  baseline.value = snapshot(form.value)
}

async function duplicate(): Promise<void> {
  if (!form.value) return
  if (!(await guard())) return
  const copy = fromApi(toInput(form.value))
  copy.name = `${copy.name}（副本）`
  selectedId.value = null
  form.value = copy
  baseline.value = '' // 副本一开始就算有改动，提醒保存
}

const importFolderId = ref<number | null>(null)
function openImport(folderId: number | null): void {
  importFolderId.value = folderId
  importVisible.value = true
}
async function onImported(result: CurlImport): Promise<void> {
  if (!(await guard())) return
  selectedId.value = null
  form.value = fromApi({ ...result.input, folderId: importFolderId.value })
  baseline.value = ''
  ElMessage.success(`已填入 ${result.input.method} ${result.input.path}，改好名字后保存`)
}

async function save(): Promise<void> {
  if (!form.value) return
  const input = toInput(form.value)
  if (!input.name) {
    ElMessage.warning('请填写接口名称')
    return
  }
  if (!input.path.startsWith('/')) {
    ElMessage.warning('路径必须以 / 开头')
    return
  }
  saving.value = true
  try {
    const saved = selectedId.value === null ? await apisApi.create(input) : await apisApi.update(selectedId.value, input)
    ElMessage.success('已保存')
    await load()
    open(saved)
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    saving.value = false
  }
}

async function del(): Promise<void> {
  const api = items.value.find((a) => a.id === selectedId.value)
  if (!api) return
  await remove(api)
  // 被流程引用时删除会被拒绝（409），列表里还在；真删掉了才清空右栏
  if (!items.value.some((a) => a.id === api.id)) {
    selectedId.value = null
    form.value = null
    if (items.value.length > 0) open(items.value[0])
  }
}
</script>

<template>
  <div class="page apis-page">
    <PageHeader
      title="接口"
    >
      <DebugEnvBar />
    </PageHeader>
    <div class="workbench">
      <ApiList
        class="workbench-list"
        :items="items"
        :folders="folders"
        :selected-id="selectedId"
        :draft-folder-id="draftFolderId"
        :loading="loading"
        @select="select"
        @create="create"
        @import="openImport"
        @create-folder="createFolder"
        @rename-folder="renameFolder"
        @delete-folder="deleteFolder"
      />
      <section class="workbench-main">
        <ApiEditor
          v-if="form"
          v-model="form"
          :is-new="isNew"
          :dirty="dirty"
          :saving="saving"
          :folder-options="folderSelectOptions"
          :producers="producers"
          @save="save"
          @duplicate="duplicate"
          @delete="del"
        />
        <div v-else class="workbench-empty">
          <p class="muted">选择或新建接口</p>
        </div>
      </section>
    </div>
    <CurlImportDialog v-model="importVisible" @imported="onImported" />
  </div>
</template>

<style scoped>
.apis-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px);
}
.workbench {
  display: grid;
  flex: 1;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}
.workbench-list,
.workbench-main {
  min-height: 0;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  background: #fff;
}
.workbench-main {
  overflow-y: auto;
}
.workbench-empty {
  padding: 80px 24px;
  text-align: center;
  line-height: 1.8;
}
.workbench-empty p {
  margin: 0;
}
@media (max-width: 960px) {
  .apis-page {
    height: auto;
  }
  .workbench {
    grid-template-columns: 1fr;
  }
  .workbench-list {
    max-height: 320px;
  }
}
</style>
