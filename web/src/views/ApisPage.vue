<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, apisApi, foldersApi, type ApiDef, type Folder } from '../api'
import { useResourceList } from '../composables/useResourceList'
import { confirmAction, errorMessage, showError } from '../utils/feedback'
import { emptyForm, formProblem, fromApi, snapshot, toInput, type ApiForm } from '../utils/api-form'
import type { CurlImport } from '../utils/curl'
import { buildFolderTree, folderOptions, folderPath } from '../utils/folders'
import { useApiIndex } from '../composables/useApiIndex'
import PageHeader from '../components/PageHeader.vue'
import ApiList from '../components/apis/ApiList.vue'
import ApiEditor from '../components/apis/ApiEditor.vue'
import CurlImportDialog from '../components/apis/CurlImportDialog.vue'
import DebugEnvBar from '../components/debug/DebugEnvBar.vue'

const { items, loading, load, remove } = useResourceList(apisApi, '接口', 'api')

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
const current = computed(() => items.value.find((a) => a.id === selectedId.value))
const usedBy = computed(() => current.value?.usedBy ?? [])
const brokenRefs = computed(() => current.value?.brokenRefs ?? [])
const dirty = computed(() => form.value !== null && snapshot(form.value) !== baseline.value)
/** 正在新建时，新接口在树里的位置（跟着表单里的所属文件夹走） */
const draftFolderId = computed<number | null | undefined>(() => (isNew.value ? (form.value?.folderId ?? null) : undefined))

// 上次打开的接口：地址里的 ?id= 优先，其次是本地记录，都没有（或已被删除）时打开第一个
const route = useRoute()
const router = useRouter()
const LAST_KEY = 'perf-console.apis.lastId'
function readLast(): number | null {
  try {
    const id = Number(localStorage.getItem(LAST_KEY))
    return Number.isInteger(id) && id > 0 ? id : null
  } catch {
    return null
  }
}
function writeLast(id: number): void {
  try {
    localStorage.setItem(LAST_KEY, String(id))
  } catch {
    // 存不了只是下次不能回到这里
  }
}
const queryId = (): number | null => {
  const id = Number(route.query.id)
  return Number.isInteger(id) && id > 0 ? id : null
}
function syncQuery(id: number | null): void {
  const query = { ...route.query }
  if (id === null) delete query.id
  else query.id = String(id)
  if (query.id !== route.query.id) void router.replace({ query })
}

watch(items, (list) => {
  if (form.value !== null || selectedId.value !== null || list.length === 0) return
  const wanted = queryId() ?? readLast()
  open(list.find((a) => a.id === wanted) ?? list[0])
})
// 在页面上时地址里的 id 变了：粘贴了另一个接口的链接就打开它；点侧栏菜单回到 /apis 时把当前接口补回地址
watch(queryId, (id) => {
  if (id === null) {
    if (selectedId.value !== null) syncQuery(selectedId.value)
    return
  }
  const api = items.value.find((a) => a.id === id)
  if (!api || api.id === selectedId.value) return
  // 放弃修改时选了"取消"，地址要回到还在编辑的接口
  void select(api).then(() => {
    if (selectedId.value !== null && selectedId.value !== queryId()) syncQuery(selectedId.value)
  })
})

function open(api: ApiDef): void {
  cancelAutoSave()
  selectedId.value = api.id
  form.value = fromApi(api)
  baseline.value = snapshot(form.value)
  writeLast(api.id)
  syncQuery(api.id)
}

// ---- 自动保存：已保存的接口改动后停顿一会儿就保存；新接口还没有名字，仍然手动保存 ----
const AUTO_SAVE_DELAY_MS = 800
const saveStatus = ref<'saving' | 'saved' | 'error' | null>(null)
const saveError = ref('')
let timer: number | undefined
let inflight: Promise<boolean> | null = null

function cancelAutoSave(): void {
  window.clearTimeout(timer)
  saveStatus.value = null
  saveError.value = ''
}
function localProblem(f: ApiForm): string | null {
  const input = toInput(f)
  if (!input.name) return '请填写接口名称'
  if (!input.path.startsWith('/')) return '路径必须以 / 开头'
  return formProblem(f)
}
function failure(e: unknown): string {
  return e instanceof ApiError && e.details.length > 0 ? e.details.join('；') : errorMessage(e)
}

watch(
  form,
  () => {
    if (selectedId.value === null || !dirty.value) return
    window.clearTimeout(timer)
    timer = window.setTimeout(() => void autoSave(), AUTO_SAVE_DELAY_MS)
  },
  { deep: true },
)

/** 把当前接口的改动存下来；没有改动也算成功。同一时间只有一个保存在进行。 */
async function autoSave(): Promise<boolean> {
  window.clearTimeout(timer)
  if (inflight) await inflight
  if (form.value === null || selectedId.value === null || !dirty.value) return true
  const problem = localProblem(form.value)
  if (problem) {
    saveStatus.value = 'error'
    saveError.value = problem
    return false
  }
  const id = selectedId.value
  const sent = snapshot(form.value)
  const input = toInput(form.value)
  saveStatus.value = 'saving'
  inflight = (async () => {
    try {
      const saved = await apisApi.update(id, input)
      // 列表里换成新的，树上的名称、路径、所属文件夹跟着变；表单不动，保存期间继续输入的内容不会被覆盖
      items.value = items.value.map((a) => (a.id === saved.id ? saved : a))
      if (selectedId.value === id) {
        baseline.value = sent
        saveStatus.value = 'saved'
        saveError.value = ''
      }
      return true
    } catch (e) {
      if (selectedId.value === id) {
        saveStatus.value = 'error'
        saveError.value = failure(e)
      }
      return false
    }
  })()
  const ok = await inflight
  inflight = null
  // 保存期间又改了：接着排下一次
  if (ok && selectedId.value === id && dirty.value) {
    timer = window.setTimeout(() => void autoSave(), AUTO_SAVE_DELAY_MS)
  }
  return ok
}

/** 离开当前接口之前：已保存的接口先把改动存下来，存不了再问；新接口没保存就问要不要放弃。 */
async function guard(): Promise<boolean> {
  if (!dirty.value) return true
  if (selectedId.value !== null) {
    if (await autoSave()) return true
    return confirmAction(`当前接口的修改没能保存：${saveError.value}。放弃这些修改吗？`, '未保存的修改', true)
  }
  return confirmAction('新接口还没有保存，放弃吗？', '未保存的修改', true)
}

onBeforeRouteLeave(() => guard())
function onBeforeUnload(e: BeforeUnloadEvent): void {
  if (!dirty.value) return
  if (selectedId.value !== null) void autoSave()
  e.preventDefault()
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.clearTimeout(timer)
})

async function select(api: ApiDef): Promise<void> {
  if (api.id === selectedId.value) return
  if (!(await guard())) return
  open(api)
}

function startDraft(draft: ApiForm, base: string): void {
  cancelAutoSave()
  selectedId.value = null
  form.value = draft
  baseline.value = base
  syncQuery(null)
}

async function create(folderId: number | null): Promise<void> {
  if (!(await guard())) return
  const draft = emptyForm(folderId)
  startDraft(draft, snapshot(draft))
}

async function duplicate(): Promise<void> {
  if (!form.value) return
  if (!(await guard())) return
  const copy = fromApi(toInput(form.value))
  copy.name = `${copy.name}（副本）`
  startDraft(copy, '') // 副本一开始就算有改动，提醒保存
}

const importFolderId = ref<number | null>(null)
function openImport(folderId: number | null): void {
  importFolderId.value = folderId
  importVisible.value = true
}
async function onImported(result: CurlImport): Promise<void> {
  if (!(await guard())) return
  startDraft(fromApi({ ...result.input, folderId: importFolderId.value }), '')
  ElMessage.success(`已填入 ${result.input.method} ${result.input.path}，改好名字后保存`)
}

async function save(): Promise<void> {
  if (!form.value) return
  // 已保存的接口：立即保存（Ctrl + S），结果显示在名称旁边
  if (selectedId.value !== null) {
    await autoSave()
    return
  }
  const input = toInput(form.value)
  if (!input.name) {
    ElMessage.warning('请填写接口名称')
    return
  }
  if (!input.path.startsWith('/')) {
    ElMessage.warning('路径必须以 / 开头')
    return
  }
  const problem = formProblem(form.value)
  if (problem) {
    ElMessage.warning(problem)
    return
  }
  saving.value = true
  try {
    const saved = await apisApi.create(input)
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
    cancelAutoSave()
    selectedId.value = null
    form.value = null
    if (items.value.length > 0) open(items.value[0])
    else syncQuery(null)
  }
}
</script>

<template>
  <div class="page apis-page">
    <PageHeader>
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
          :api-id="selectedId"
          :is-new="isNew"
          :dirty="dirty"
          :saving="saving"
          :save-status="saveStatus"
          :save-error="saveError"
          :used-by="usedBy"
          :broken-refs="brokenRefs"
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
