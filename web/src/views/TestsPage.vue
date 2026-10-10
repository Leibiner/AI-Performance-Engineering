<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Plus, VideoPlay } from '@element-plus/icons-vue'
import { flowsApi, testsApi, type Flow, type TestDef, type TestInput } from '../api'
import { useResourceList } from '../composables/useResourceList'
import { showError } from '../utils/feedback'
import { formatPercent, formatTime, percentToRatio, ratioToPercent } from '../utils/format'
import { sloItems } from '../utils/slo'
import PageHeader from '../components/PageHeader.vue'
import RunDialog from '../components/RunDialog.vue'
import VerdictTag from '../components/VerdictTag.vue'

const { items, loading, load, remove } = useResourceList(testsApi, '测试')
const route = useRoute()
const router = useRouter()

// 从别的页面点过来（/tests?edit=2）：列表加载完后直接打开这个测试的编辑框
watch(items, (list) => {
  const id = Number(route.query.edit)
  const test = Number.isInteger(id) ? list.find((t) => t.id === id) : undefined
  if (!test) return
  void router.replace({ query: {} })
  openEdit(test)
})

const flows = ref<Flow[]>([])
async function loadFlows(): Promise<void> {
  try {
    flows.value = await flowsApi.list()
  } catch (e) {
    showError(e, '加载业务流程失败')
  }
}
onMounted(loadFlows)

interface FlowRow {
  flowId: number | undefined
  weight: number | undefined
}
interface FormState {
  name: string
  note: string
  flows: FlowRow[]
  p95Ms: number | undefined
  p99Ms: number | undefined
  /** 界面上按百分数填写，保存时转成 0~1 的比例 */
  errorRatePct: number | undefined
  checksRatePct: number | undefined
}

function emptyForm(): FormState {
  return {
    name: '',
    note: '',
    flows: [{ flowId: undefined, weight: 1 }],
    p95Ms: undefined,
    p99Ms: undefined,
    errorRatePct: undefined,
    checksRatePct: undefined,
  }
}

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
/** 编辑中的测试里引用了已删除流程的 id（后端返回 flowName 为 null） */
const missingFlowIds = ref<Set<number>>(new Set())
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormState>(emptyForm())

const rules: FormRules<FormState> = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
}

const totalWeight = computed(() => form.flows.reduce((sum, f) => sum + (f.weight ?? 0), 0))
function share(weight: number | undefined): string {
  if (!weight || totalWeight.value <= 0) return ''
  return formatPercent(weight / totalWeight.value, 1)
}

function openCreate(): void {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
  void loadFlows()
}

function openEdit(row: TestDef): void {
  editingId.value = row.id
  missingFlowIds.value = new Set((row.flows ?? []).filter((f) => f.flowName === null).map((f) => f.flowId))
  Object.assign(form, {
    name: row.name,
    note: row.note ?? '',
    flows: (row.flows ?? []).map((f) => ({ flowId: f.flowId, weight: f.weight })),
    p95Ms: row.slo?.p95Ms ?? undefined,
    p99Ms: row.slo?.p99Ms ?? undefined,
    errorRatePct: ratioToPercent(row.slo?.errorRate),
    checksRatePct: ratioToPercent(row.slo?.checksRate),
  } satisfies FormState)
  dialogVisible.value = true
  void loadFlows()
}

function addFlow(): void {
  form.flows.push({ flowId: undefined, weight: 1 })
}

async function save(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (form.flows.length === 0) {
    ElMessage.warning('至少需要选择 1 个业务流程')
    return
  }
  for (const [index, f] of form.flows.entries()) {
    if (f.flowId === undefined || f.flowId === null) {
      ElMessage.warning(`第 ${index + 1} 行还没有选择业务流程`)
      return
    }
    if (typeof f.weight !== 'number' || f.weight <= 0) {
      ElMessage.warning(`第 ${index + 1} 行的权重必须大于 0`)
      return
    }
  }
  const ids = form.flows.map((f) => f.flowId)
  if (new Set(ids).size !== ids.length) {
    ElMessage.warning('同一个业务流程只需要选一次，用权重调整比例')
    return
  }

  const input: TestInput = {
    name: form.name.trim(),
    note: form.note,
    flows: form.flows.map((f) => ({ flowId: f.flowId as number, weight: f.weight as number })),
    slo: {
      p95Ms: form.p95Ms ?? null,
      p99Ms: form.p99Ms ?? null,
      errorRate: percentToRatio(form.errorRatePct),
      checksRate: percentToRatio(form.checksRatePct),
    },
  }
  saving.value = true
  try {
    if (editingId.value === null) await testsApi.create(input)
    else await testsApi.update(editingId.value, input)
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    saving.value = false
  }
}

function flowShares(test: TestDef): { name: string; share: string; missing: boolean }[] {
  const list = test.flows ?? []
  const total = list.reduce((sum, f) => sum + f.weight, 0)
  return list.map((f) => ({
    name: f.flowName ?? `流程已删除（#${f.flowId}）`,
    missing: f.flowName === null,
    share: total > 0 ? formatPercent(f.weight / total, 1) : '',
  }))
}

const runDialogVisible = ref(false)
const runTarget = ref<TestDef | null>(null)
function openRun(row: TestDef): void {
  runTarget.value = row
  runDialogVisible.value = true
}
</script>

<template>
  <div class="page">
    <PageHeader>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建测试</el-button>
    </PageHeader>

    <div class="panel">
      <el-table v-loading="loading" :data="items" empty-text="暂无数据">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="业务流程（占比）" min-width="200">
          <template #default="{ row }">
            <div v-for="(f, index) in flowShares(row as TestDef)" :key="index">
              <span :class="{ 'is-missing': f.missing }">{{ f.name }}</span> <span class="muted num">{{ f.share }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="验收标准" min-width="200">
          <template #default="{ row }">
            <template v-if="sloItems((row as TestDef).slo).length">
              <div v-for="item in sloItems((row as TestDef).slo)" :key="item" class="num">{{ item }}</div>
            </template>
            <span v-else class="muted">未设置</span>
          </template>
        </el-table-column>
        <el-table-column label="最近一次运行" min-width="190">
          <template #default="{ row }">
            <router-link v-if="(row as TestDef).lastRun" class="last-run" :to="`/runs/${row.lastRun.runId}`">
              <VerdictTag v-if="row.lastRun.verdict" :verdict="row.lastRun.verdict" />
              <el-tag v-else type="primary" effect="dark" size="small" round>运行中</el-tag>
              <span class="muted num">{{ formatTime(row.lastRun.startedAt) }}</span>
            </router-link>
            <span v-else class="muted">还没有运行过</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" :icon="VideoPlay" @click="openRun(row as TestDef)">运行</el-button>
            <el-button link type="primary" @click="openEdit(row as TestDef)">编辑</el-button>
            <el-button link type="danger" @click="remove(row as TestDef)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建测试' : '编辑测试'"
      width="760px"
      top="6vh"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：百度首页冒烟" />
        </el-form-item>

        <el-form-item label="业务流程" required>
          <div class="row-list">
            <div class="row-item row-head">
              <span class="grow">流程</span>
              <span style="width: 150px">权重</span>
              <span style="width: 70px">占比</span>
              <span style="width: 32px" />
            </div>
            <div v-for="(item, index) in form.flows" :key="index" class="row-item">
              <el-select
                v-model="item.flowId"
                :class="['grow', { 'is-missing': item.flowId !== undefined && missingFlowIds.has(item.flowId) && !flows.some((f) => f.id === item.flowId) }]"
                filterable
                placeholder="选择业务流程"
                no-data-text="还没有业务流程，请先到“业务流程”页面新建"
              >
                <el-option v-for="flow in flows" :key="flow.id" :label="flow.name" :value="flow.id" />
                <el-option
                  v-if="item.flowId !== undefined && missingFlowIds.has(item.flowId) && !flows.some((f) => f.id === item.flowId)"
                  :value="item.flowId"
                  :label="`流程已删除（#${item.flowId}）`"
                />
              </el-select>
              <el-input-number v-model="item.weight" :min="0" :step="1" controls-position="right" style="width: 150px" />
              <span class="muted num" style="width: 70px">{{ share(item.weight) }}</span>
              <el-button
                :icon="Delete"
                circle
                text
                title="删除这一行"
                :disabled="form.flows.length <= 1"
                @click="form.flows.splice(index, 1)"
              />
            </div>
            <el-button :icon="Plus" size="small" @click="addFlow">添加流程</el-button>
          </div>
        </el-form-item>

        <el-divider content-position="left">验收标准（留空表示不设这一项）</el-divider>

        <el-form-item label="p95 响应时间">
          <span class="op">&lt;</span>
          <el-input-number v-model="form.p95Ms" :min="0" :controls="false" placeholder="不设" />
          <span class="unit">毫秒</span>
        </el-form-item>
        <el-form-item label="p99 响应时间">
          <span class="op">&lt;</span>
          <el-input-number v-model="form.p99Ms" :min="0" :controls="false" placeholder="不设" />
          <span class="unit">毫秒</span>
        </el-form-item>
        <el-form-item label="错误率">
          <span class="op">&lt;</span>
          <el-input-number v-model="form.errorRatePct" :min="0" :max="100" :controls="false" placeholder="不设" />
          <span class="unit">%</span>
        </el-form-item>
        <el-form-item label="检查通过率">
          <span class="op">≥</span>
          <el-input-number v-model="form.checksRatePct" :min="0" :max="100" :controls="false" placeholder="默认 99" />
          <span class="unit">%</span>
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <RunDialog v-model="runDialogVisible" :test="runTarget" />
  </div>
</template>

<style scoped>
.is-missing {
  color: var(--el-color-danger);
  text-decoration: line-through;
}
.el-select.is-missing {
  text-decoration: none;
}
.el-select.is-missing :deep(.el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.last-run {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: inherit;
  text-decoration: none;
}
.last-run:hover .muted {
  color: var(--el-color-primary);
}
.op {
  display: inline-block;
  width: 22px;
  color: var(--ink-muted);
  font-size: 15px;
}
</style>
