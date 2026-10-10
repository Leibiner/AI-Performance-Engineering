<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { ArrowDown, ArrowUp, Delete, Plus, VideoPlay } from '@element-plus/icons-vue'
import {
  apisApi,
  flowsApi,
  foldersApi,
  type ApiDef,
  type DatasetOnExhausted,
  type DatasetPick,
  type Flow,
  type FlowInput,
  type Folder,
} from '../api'
import { useDatasetList } from '../composables/useDatasetList'
import { useDebugContext } from '../composables/useDebugContext'
import { useResourceList } from '../composables/useResourceList'
import { confirmDeleteFlow } from '../utils/dependencies'
import { showError } from '../utils/feedback'
import { folderPath } from '../utils/folders'
import { EXHAUSTED_OPTIONS, INIT_SEGMENT_TITLE, MAIN_SEGMENT_TITLE, PICK_LABELS, PICK_OPTIONS } from '../utils/test-data'
import { analyzeFlow, refResolver, type FlowVarModel } from '../utils/var-sources'
import { isValidVarName } from '../utils/vars'
import PageHeader from '../components/PageHeader.vue'
import VarInput from '../components/VarInput.vue'
import DebugEnvBar from '../components/debug/DebugEnvBar.vue'
import EnvPicker from '../components/debug/EnvPicker.vue'
import FlowDebugDialog from '../components/debug/FlowDebugDialog.vue'
import FlowStepList, { type ApiGroup, type StepRow } from '../components/flows/FlowStepList.vue'

const { items, loading, load, remove } = useResourceList(flowsApi, '业务流程')
const route = useRoute()
const router = useRouter()

// 从别的页面点过来（/flows?edit=3）：列表加载完后直接打开这个流程的编辑框
watch(items, (list) => {
  const id = Number(route.query.edit)
  const flow = Number.isInteger(id) ? list.find((f) => f.id === id) : undefined
  if (!flow) return
  void router.replace({ query: {} })
  openEdit(flow)
})

/** 被测试引用也可以删：先列出会失效的测试，确认后只删这个流程 */
async function del(row: Flow): Promise<void> {
  let confirmed = false
  try {
    const fresh = await flowsApi.get(row.id)
    if (fresh.usedBy?.length) {
      if (!(await confirmDeleteFlow(router, fresh.name, fresh.usedBy))) return
      confirmed = true
    }
  } catch (e) {
    showError(e, '删除失败')
    return
  }
  await remove(row, confirmed)
}
const ctx = useDebugContext()
const { datasets, refresh: refreshDatasets } = useDatasetList()

// 步骤里要选接口；接口按文件夹分组显示
const apis = ref<ApiDef[]>([])
const folders = ref<Folder[]>([])
async function loadApis(): Promise<void> {
  try {
    const [a, f] = await Promise.all([apisApi.list(), foldersApi.list()])
    apis.value = a
    folders.value = f
  } catch (e) {
    showError(e, '加载接口失败')
  }
}
onMounted(loadApis)

const apiGroups = computed<ApiGroup[] | null>(() => {
  if (!folders.value.length) return null
  const groups = new Map<string, ApiDef[]>()
  for (const api of apis.value) {
    const label = folderPath(folders.value, api.folderId) || '（根目录）'
    const list = groups.get(label)
    if (list) list.push(api)
    else groups.set(label, [api])
  }
  return [...groups.entries()]
    .map(([label, list]) => ({ label, apis: list }))
    .sort((a, b) => (a.label === '（根目录）' ? 1 : b.label === '（根目录）' ? -1 : a.label.localeCompare(b.label, 'zh-Hans-CN')))
})
const apiById = computed(() => new Map(apis.value.map((a) => [a.id, a])))

interface DatasetRow {
  key: number
  datasetId: number | undefined
  pick: DatasetPick
  onExhausted: DatasetOnExhausted
}
interface VariableRow {
  key: number
  name: string
  value: string
}
interface FormState {
  name: string
  note: string
  datasets: DatasetRow[]
  variables: VariableRow[]
  initSteps: StepRow[]
  reinitSec: number | null | undefined
  steps: StepRow[]
}

let rowSeq = 0
const nextKey = () => (rowSeq += 1)
const stepRow = (apiId?: number, thinkTimeMs = 0): StepRow => ({ key: nextKey(), apiId, thinkTimeMs })

function emptyForm(): FormState {
  return { name: '', note: '', datasets: [], variables: [], initSteps: [], reinitSec: null, steps: [stepRow()] }
}

const dialogVisible = ref(false)

// 试跑：用真实 k6 把流程跑一次迭代
const debugVisible = ref(false)
const debugFlow = ref<Flow | null>(null)
function openDebug(row: Flow): void {
  debugFlow.value = row
  debugVisible.value = true
}
const editingId = ref<number | null>(null)
/** 编辑中的流程原样：数据集列表还没取到时，用它带的列名做变量检查 */
const editingFlow = ref<Flow | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormState>(emptyForm())

const rules: FormRules<FormState> = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
}

function openCreate(): void {
  editingId.value = null
  editingFlow.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
  void loadApis()
  void refreshDatasets()
}

function openEdit(row: Flow): void {
  editingId.value = row.id
  editingFlow.value = row
  Object.assign(form, {
    name: row.name,
    note: row.note ?? '',
    datasets: (row.datasets ?? []).map((d) => ({
      key: nextKey(),
      datasetId: d.datasetId,
      pick: d.pick,
      onExhausted: d.onExhausted,
    })),
    variables: (row.variables ?? []).map((v) => ({ key: nextKey(), name: v.name, value: v.value })),
    initSteps: (row.initSteps ?? []).map((s) => stepRow(s.apiId, s.thinkTimeMs)),
    reinitSec: row.reinitSec ?? null,
    steps: (row.steps ?? []).map((s) => stepRow(s.apiId, s.thinkTimeMs)),
  } satisfies FormState)
  dialogVisible.value = true
  void loadApis()
  void refreshDatasets()
}

/** 初始化段的最后一步和每次迭代的第一步在执行顺序上相邻，移动时放在那里，顺序不乱 */
function moveToMain(index: number): void {
  const [step] = form.initSteps.splice(index, 1)
  form.steps.unshift(step)
}
function moveToInit(index: number): void {
  const [step] = form.steps.splice(index, 1)
  form.initSteps.push(step)
}

/** 编辑中的流程里引用了已删除接口的步骤（后端返回 apiName 为 null） */
const missingApiIds = computed(
  () =>
    new Set(
      [...(editingFlow.value?.initSteps ?? []), ...(editingFlow.value?.steps ?? [])]
        .filter((s) => s.apiName === null)
        .map((s) => s.apiId),
    ),
)
function datasetMissing(id: number | undefined): boolean {
  if (id === undefined || datasets.value.some((d) => d.id === id)) return false
  return editingFlow.value?.datasets?.some((b) => b.datasetId === id && b.datasetName === null) ?? false
}
/** 列表里每个流程的失效引用：已删除的接口、数据集 */
function brokenRefs(flow: Flow): string[] {
  const out = [...(flow.initSteps ?? []), ...(flow.steps ?? [])].filter((s) => s.apiName === null).map((s) => `接口 #${s.apiId}`)
  out.push(...(flow.datasets ?? []).filter((b) => b.datasetName === null).map((b) => `数据集 #${b.datasetId}`))
  return out
}

function datasetInfo(id: number | undefined): { name: string; columns: string[]; rowCount: number | null } | null {
  if (id === undefined) return null
  const d = datasets.value.find((x) => x.id === id)
  if (d) return { name: d.name, columns: d.columns, rowCount: d.rowCount }
  const bound = editingFlow.value?.datasets?.find((x) => x.datasetId === id)
  return bound ? { name: bound.datasetName ?? `数据集已删除（#${id}）`, columns: bound.columns ?? [], rowCount: bound.rowCount ?? null } : null
}
function addDataset(): void {
  form.datasets.push({ key: nextKey(), datasetId: undefined, pick: 'sequential', onExhausted: 'recycle' })
}
function onPickChange(row: DatasetRow): void {
  if (row.pick === 'random') row.onExhausted = 'recycle'
}
const boundElsewhere = (id: number, row: DatasetRow) => form.datasets.some((b) => b !== row && b.datasetId === id)

/** 同一流程里列名不能重复，也不能和流程变量重名 */
const columnConflicts = computed(() => {
  const count = new Map<string, number>()
  for (const b of form.datasets) for (const c of datasetInfo(b.datasetId)?.columns ?? []) count.set(c, (count.get(c) ?? 0) + 1)
  const names = new Set(form.variables.map((v) => v.name.trim()).filter(Boolean))
  return new Set([...count.entries()].filter(([c, n]) => n > 1 || names.has(c)).map(([c]) => c))
})

function addVariable(): void {
  form.variables.push({ key: nextKey(), name: '', value: '' })
}
function moveVariable(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= form.variables.length) return
  const [row] = form.variables.splice(index, 1)
  form.variables.splice(target, 0, row)
}
function variableNameError(index: number): string | null {
  const row = form.variables[index]
  const name = row.name.trim()
  if (!name) return row.value ? '请填写变量名' : null
  if (!isValidVarName(name)) return '变量名只能用字母（含中文）、数字、下划线'
  if (form.variables.some((v, i) => i !== index && v.name.trim() === name)) return '变量名重复'
  const owner = form.datasets.map((b) => datasetInfo(b.datasetId)).find((d) => d?.columns.includes(name))
  if (owner) return `和数据集「${owner.name}」的列重名`
  return null
}

const varModel = computed<FlowVarModel>(() => {
  const env = ctx.environment.value
  const pick = (s: StepRow) => (s.apiId === undefined ? null : (apiById.value.get(s.apiId) ?? null))
  return {
    env: env ? { name: env.name, variables: env.variables ?? {}, headers: env.headers ?? {} } : null,
    datasets: form.datasets.flatMap((b) => {
      const d = datasetInfo(b.datasetId)
      return d ? [{ name: d.name, columns: d.columns }] : []
    }),
    variables: form.variables.map((v) => ({ name: v.name, value: v.value })),
    initSteps: form.initSteps.map(pick),
    steps: form.steps.map(pick),
    allApis: apis.value,
  }
})
const report = computed(() => analyzeFlow(varModel.value))
const variableResolvers = computed(() =>
  form.variables.map((_, index) => refResolver(varModel.value, { kind: 'variable', index })),
)

async function save(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (form.steps.length === 0) {
    ElMessage.warning(`「${MAIN_SEGMENT_TITLE}」至少需要 1 个步骤`)
    return
  }
  const unpicked = (list: StepRow[]) => list.findIndex((s) => s.apiId === undefined || s.apiId === null)
  const initMissing = unpicked(form.initSteps)
  if (initMissing >= 0) {
    ElMessage.warning(`初始化第 ${initMissing + 1} 步还没有选择接口`)
    return
  }
  const missing = unpicked(form.steps)
  if (missing >= 0) {
    ElMessage.warning(`第 ${missing + 1} 步还没有选择接口`)
    return
  }
  const unbound = form.datasets.findIndex((b) => b.datasetId === undefined)
  if (unbound >= 0) {
    ElMessage.warning(`第 ${unbound + 1} 个数据集绑定还没有选择数据集`)
    return
  }
  const badVar = form.variables.findIndex((_, i) => variableNameError(i) !== null)
  if (badVar >= 0) {
    ElMessage.warning(`流程变量第 ${badVar + 1} 行：${variableNameError(badVar)}`)
    return
  }
  const toSteps = (list: StepRow[]) => list.map((s) => ({ apiId: s.apiId as number, thinkTimeMs: s.thinkTimeMs ?? 0 }))
  const input: FlowInput = {
    name: form.name.trim(),
    note: form.note,
    datasets: form.datasets.map((b) => ({
      datasetId: b.datasetId as number,
      pick: b.pick,
      onExhausted: b.pick === 'random' ? 'recycle' : b.onExhausted,
    })),
    variables: form.variables.filter((v) => v.name.trim() || v.value).map((v) => ({ name: v.name.trim(), value: v.value })),
    initSteps: toSteps(form.initSteps),
    reinitSec: form.initSteps.length && typeof form.reinitSec === 'number' ? form.reinitSec : null,
    steps: toSteps(form.steps),
  }
  saving.value = true
  try {
    if (editingId.value === null) await flowsApi.create(input)
    else await flowsApi.update(editingId.value, input)
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    saving.value = false
  }
}

const datasetTitle = (row: Flow) =>
  (row.datasets ?? []).map((d) => `${d.datasetName ?? `#${d.datasetId}`}（${PICK_LABELS[d.pick] ?? d.pick}）`).join('\n')
</script>

<template>
  <div class="page">
    <PageHeader title="业务流程">
      <DebugEnvBar />
      <el-button type="primary" :icon="Plus" @click="openCreate">新建流程</el-button>
    </PageHeader>

    <div class="panel">
      <el-table v-loading="loading" :data="items" empty-text="暂无数据">
        <el-table-column label="名称" min-width="180">
          <template #default="{ row }">
            <span>{{ (row as Flow).name }}</span>
            <el-tag
              v-if="brokenRefs(row as Flow).length"
              size="small"
              type="danger"
              effect="plain"
              class="flow-tag"
              :title="`已删除：${brokenRefs(row as Flow).join('、')}`"
              disable-transitions
            >
              失效 {{ brokenRefs(row as Flow).length }}
            </el-tag>
            <el-tag
              v-if="(row as Flow).datasets?.length"
              size="small"
              type="info"
              effect="plain"
              class="flow-tag"
              :title="datasetTitle(row as Flow)"
              disable-transitions
            >
              数据集 {{ (row as Flow).datasets.length }}
            </el-tag>
            <el-tag
              v-if="(row as Flow).usedBy?.length"
              size="small"
              effect="plain"
              class="flow-tag"
              :title="(row as Flow).usedBy!.map((t) => t.testName).join('、')"
              disable-transitions
            >
              测试 {{ (row as Flow).usedBy!.length }}
            </el-tag>
            <el-tag
              v-if="(row as Flow).variables?.length"
              size="small"
              type="info"
              effect="plain"
              class="flow-tag"
              :title="(row as Flow).variables.map((v) => v.name).join('、')"
              disable-transitions
            >
              变量 {{ (row as Flow).variables.length }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="步骤" min-width="420">
          <template #default="{ row }">
            <div v-if="(row as Flow).steps?.length || (row as Flow).initSteps?.length" class="step-chain">
              <template v-if="(row as Flow).initSteps?.length">
                <span class="init-label" :title="INIT_SEGMENT_TITLE">初始化</span>
                <span
                  v-for="(step, index) in (row as Flow).initSteps"
                  :key="`i${index}`"
                  :class="['step-chip', 'is-init', { 'is-missing': step.apiName === null }]"
                  :title="`${step.method ?? ''} ${step.path ?? ''}`"
                >
                  <span class="step-no">{{ index + 1 }}</span>
                  {{ step.apiName ?? `接口已删除（#${step.apiId}）` }}
                </span>
                <span class="step-divider" />
              </template>
              <template v-for="(step, index) in (row as Flow).steps" :key="index">
                <span v-if="index > 0" class="step-arrow">→</span>
                <span :class="['step-chip', { 'is-missing': step.apiName === null }]" :title="`${step.method ?? ''} ${step.path ?? ''}`">
                  <span class="step-no">{{ index + 1 }}</span>
                  {{ step.apiName ?? `接口已删除（#${step.apiId}）` }}
                  <span v-if="step.thinkTimeMs > 0" class="muted">· 等待 {{ step.thinkTimeMs }} ms</span>
                </span>
              </template>
            </div>
            <span v-else class="muted">没有步骤</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="VideoPlay" @click="openDebug(row as Flow)">试跑</el-button>
            <el-button link type="primary" @click="openEdit(row as Flow)">编辑</el-button>
            <el-button link type="danger" @click="del(row as Flow)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <FlowDebugDialog v-model="debugVisible" :flow="debugFlow" />

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建业务流程' : '编辑业务流程'"
      width="1080px"
      top="4vh"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="flow-form">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：访问首页" />
        </el-form-item>

        <el-form-item label="数据集">
          <div class="row-list">
            <div v-if="form.datasets.length" class="row-item row-head">
              <span class="ds-set">数据集</span>
              <span class="ds-pick">取法</span>
              <span class="ds-exhaust">数据用完时</span>
              <span class="grow">列</span>
              <span class="ds-op" />
            </div>
            <div v-for="b in form.datasets" :key="b.key" class="row-item">
              <el-select
                v-model="b.datasetId"
                :class="['ds-set', { 'is-missing': datasetMissing(b.datasetId) }]"
                filterable
                placeholder="选择数据集"
                no-data-text="还没有数据集"
                @visible-change="(open: boolean) => open && refreshDatasets()"
              >
                <el-option
                  v-for="d in datasets"
                  :key="d.id"
                  :label="d.name"
                  :value="d.id"
                  :disabled="boundElsewhere(d.id, b)"
                >
                  <span class="ds-option">
                    <span>{{ d.name }}</span>
                    <span class="muted num">{{ d.rowCount }} 行</span>
                  </span>
                </el-option>
                <el-option
                  v-if="b.datasetId !== undefined && !datasets.some((d) => d.id === b.datasetId)"
                  :value="b.datasetId"
                  :label="datasetInfo(b.datasetId)?.name ?? `数据集 #${b.datasetId}`"
                />
              </el-select>
              <el-select v-model="b.pick" class="ds-pick" @change="onPickChange(b)">
                <el-option v-for="o in PICK_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
              <el-select v-model="b.onExhausted" class="ds-exhaust" :disabled="b.pick === 'random'">
                <el-option v-for="o in EXHAUSTED_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
              <div class="grow ds-columns">
                <el-tag
                  v-for="c in datasetInfo(b.datasetId)?.columns ?? []"
                  :key="c"
                  size="small"
                  :type="columnConflicts.has(c) ? 'danger' : 'info'"
                  effect="plain"
                  class="mono"
                  :title="columnConflicts.has(c) ? '列名重复' : undefined"
                  disable-transitions
                >
                  {{ c }}
                </el-tag>
              </div>
              <el-button
                :icon="Delete"
                circle
                text
                class="ds-op"
                title="删除这个绑定"
                @click="form.datasets.splice(form.datasets.indexOf(b), 1)"
              />
            </div>
            <el-button :icon="Plus" size="small" @click="addDataset">添加数据集</el-button>
          </div>
        </el-form-item>

        <el-form-item label="流程变量">
          <div class="row-list">
            <div v-for="(v, index) in form.variables" :key="v.key" class="row-item">
              <span class="row-index">{{ index + 1 }}</span>
              <el-input
                v-model="v.name"
                placeholder="名称"
                class="mono var-name"
                :class="{ 'is-invalid': variableNameError(index) }"
                :title="variableNameError(index) ?? undefined"
              />
              <div class="grow">
                <VarInput v-model="v.value" :resolve="variableResolvers[index]" placeholder="ORD{{$timestampMs}}{{$vu}}" />
              </div>
              <span class="var-ops">
                <el-button :icon="ArrowUp" circle text title="上移" :disabled="index === 0" @click="moveVariable(index, -1)" />
                <el-button
                  :icon="ArrowDown"
                  circle
                  text
                  title="下移"
                  :disabled="index === form.variables.length - 1"
                  @click="moveVariable(index, 1)"
                />
                <el-button :icon="Delete" circle text title="删除" @click="form.variables.splice(index, 1)" />
              </span>
            </div>
            <el-button :icon="Plus" size="small" @click="addVariable">添加变量</el-button>
          </div>
        </el-form-item>

        <el-form-item :label="INIT_SEGMENT_TITLE">
          <FlowStepList
            v-model="form.initSteps"
            phase="init"
            :apis="apis"
            :missing="missingApiIds"
            :groups="apiGroups"
            :checks="report.init"
            @add="form.initSteps.push(stepRow())"
            @move="moveToMain"
          />
          <div v-if="form.initSteps.length" class="reinit">
            <span class="reinit-label">重新初始化间隔（秒）</span>
            <el-input-number
              v-model="form.reinitSec"
              :min="1"
              :precision="0"
              controls-position="right"
              placeholder="不重新执行"
              class="reinit-input"
            />
          </div>
        </el-form-item>

        <el-form-item :label="MAIN_SEGMENT_TITLE" required>
          <FlowStepList
            v-model="form.steps"
            phase="main"
            :apis="apis"
            :missing="missingApiIds"
            :groups="apiGroups"
            :checks="report.main"
            @add="form.steps.push(stepRow())"
            @move="moveToInit"
          />
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="flow-footer">
          <div class="flow-footer-check">
            <span class="muted">调试环境</span>
            <EnvPicker />
            <el-popover v-if="report.problems.length" placement="top-start" :width="560" trigger="hover">
              <template #reference>
                <span class="flow-problems">{{ report.problems.length }} 处引用没有来源</span>
              </template>
              <ul class="flow-problem-list">
                <li v-for="(p, i) in report.problems" :key="i">{{ p }}</li>
              </ul>
            </el-popover>
          </div>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.step-chip.is-missing {
  border-color: var(--el-color-danger-light-5);
  color: var(--el-color-danger);
  text-decoration: line-through;
}
.ds-set.is-missing :deep(.el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.ds-set.is-missing :deep(.el-select__selected-item) {
  color: var(--el-color-danger);
}
.flow-tag {
  margin-left: 6px;
}
.step-chain {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.step-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px 2px 4px;
  border: 1px solid var(--hairline);
  border-radius: 12px;
  background: #fafbfc;
  font-size: 13px;
  line-height: 18px;
}
.step-chip.is-init {
  border-style: dashed;
  background: transparent;
  color: var(--el-text-color-regular);
}
.step-no {
  display: inline-block;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #e8ebf0;
  color: #5b6472;
  font-size: 11px;
  text-align: center;
}
.step-arrow {
  color: var(--ink-muted);
}
.init-label {
  color: var(--ink-muted);
  font-size: 12px;
}
.step-divider {
  width: 1px;
  height: 18px;
  margin: 0 4px;
  background: var(--el-border-color);
}

.flow-form :deep(.el-form-item__label) {
  font-weight: 600;
}
.ds-set {
  flex-shrink: 0;
  width: 220px;
}
.ds-pick {
  flex-shrink: 0;
  width: 160px;
}
.ds-exhaust {
  flex-shrink: 0;
  width: 120px;
}
.ds-op {
  flex-shrink: 0;
  width: 32px;
}
.ds-option {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.ds-columns {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.var-name {
  flex-shrink: 0;
  width: 180px;
}
.var-name.is-invalid :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.var-ops {
  display: inline-flex;
  flex-shrink: 0;
}
.var-ops .el-button + .el-button {
  margin-left: 0;
}
.reinit {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
}
.reinit-label {
  color: var(--el-text-color-regular);
  font-size: 13px;
}
.reinit-input {
  width: 160px;
}
.flow-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
.flow-footer-check {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 10px;
  min-width: 0;
  text-align: left;
}
.flow-footer .el-button + .el-button {
  margin-left: 0;
}
.flow-problems {
  color: var(--el-color-danger);
  font-size: 13px;
  font-weight: 600;
  cursor: default;
}
.flow-problem-list {
  max-height: 320px;
  margin: 0;
  padding-left: 18px;
  overflow: auto;
  line-height: 1.7;
}
</style>
