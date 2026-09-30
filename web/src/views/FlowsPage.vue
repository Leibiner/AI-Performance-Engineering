<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { ArrowDown, ArrowUp, Delete, Plus } from '@element-plus/icons-vue'
import { apisApi, flowsApi, type ApiDef, type Flow, type FlowInput } from '../api'
import { useResourceList } from '../composables/useResourceList'
import { showError } from '../utils/feedback'
import PageHeader from '../components/PageHeader.vue'

const { items, loading, load, remove } = useResourceList(flowsApi, '业务流程')

// 步骤里要选接口
const apis = ref<ApiDef[]>([])
async function loadApis(): Promise<void> {
  try {
    apis.value = await apisApi.list()
  } catch (e) {
    showError(e, '加载接口失败')
  }
}
onMounted(loadApis)

interface StepRow {
  apiId: number | undefined
  thinkTimeMs: number | undefined
}
interface FormState {
  name: string
  note: string
  steps: StepRow[]
}

function emptyForm(): FormState {
  return { name: '', note: '', steps: [{ apiId: undefined, thinkTimeMs: 0 }] }
}

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormState>(emptyForm())

const rules: FormRules<FormState> = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
}

function openCreate(): void {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
  void loadApis()
}

function openEdit(row: Flow): void {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    note: row.note ?? '',
    steps: (row.steps ?? []).map((s) => ({ apiId: s.apiId, thinkTimeMs: s.thinkTimeMs })),
  } satisfies FormState)
  dialogVisible.value = true
  void loadApis()
}

function addStep(): void {
  form.steps.push({ apiId: undefined, thinkTimeMs: 0 })
}
function moveStep(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= form.steps.length) return
  const [step] = form.steps.splice(index, 1)
  form.steps.splice(target, 0, step)
}

async function save(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (form.steps.length === 0) {
    ElMessage.warning('至少需要 1 个步骤')
    return
  }
  const missing = form.steps.findIndex((s) => s.apiId === undefined || s.apiId === null)
  if (missing >= 0) {
    ElMessage.warning(`第 ${missing + 1} 步还没有选择接口`)
    return
  }
  const input: FlowInput = {
    name: form.name.trim(),
    note: form.note,
    steps: form.steps.map((s) => ({ apiId: s.apiId as number, thinkTimeMs: s.thinkTimeMs ?? 0 })),
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
</script>

<template>
  <div class="page">
    <PageHeader
      title="业务流程"
      description="按顺序执行的一组接口步骤，代表一个用户会做的一件事。流程里不写并发、到达率和时长，这些在负载配置里设。"
    >
      <el-button type="primary" :icon="Plus" @click="openCreate">新建流程</el-button>
    </PageHeader>

    <div class="panel">
      <el-table v-loading="loading" :data="items" empty-text="还没有业务流程">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="步骤" min-width="420">
          <template #default="{ row }">
            <div v-if="(row as Flow).steps?.length" class="step-chain">
              <template v-for="(step, index) in (row as Flow).steps" :key="index">
                <span v-if="index > 0" class="step-arrow">→</span>
                <span class="step-chip" :title="`${step.method ?? ''} ${step.path ?? ''}`">
                  <span class="step-no">{{ index + 1 }}</span>
                  {{ step.apiName ?? `接口 #${step.apiId}` }}
                  <span v-if="step.thinkTimeMs > 0" class="muted">· 等待 {{ step.thinkTimeMs }} ms</span>
                </span>
              </template>
            </div>
            <span v-else class="muted">没有步骤</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row as Flow)">编辑</el-button>
            <el-button link type="danger" @click="remove(row as Flow)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建业务流程' : '编辑业务流程'"
      width="780px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：访问首页" />
        </el-form-item>
        <el-form-item label="步骤" required>
          <div class="row-list">
            <div class="row-item row-head">
              <span class="row-index" />
              <span class="grow">接口</span>
              <span style="width: 170px">执行后等待（毫秒）</span>
              <span style="width: 104px" />
            </div>
            <div v-for="(step, index) in form.steps" :key="index" class="row-item">
              <span class="row-index">{{ index + 1 }}</span>
              <el-select v-model="step.apiId" class="grow" filterable placeholder="选择接口" no-data-text="还没有接口，请先到“接口”页面新建">
                <el-option v-for="api in apis" :key="api.id" :label="`${api.name}（${api.method} ${api.path}）`" :value="api.id" />
              </el-select>
              <el-input-number
                v-model="step.thinkTimeMs"
                :min="0"
                :step="100"
                :precision="0"
                controls-position="right"
                style="width: 170px"
              />
              <el-button :icon="ArrowUp" circle text title="上移" :disabled="index === 0" @click="moveStep(index, -1)" />
              <el-button
                :icon="ArrowDown"
                circle
                text
                title="下移"
                :disabled="index === form.steps.length - 1"
                style="margin-left: 0"
                @click="moveStep(index, 1)"
              />
              <el-button :icon="Delete" circle text title="删除这一步" style="margin-left: 0" @click="form.steps.splice(index, 1)" />
            </div>
            <el-button :icon="Plus" size="small" @click="addStep">添加步骤</el-button>
          </div>
          <div class="form-hint">
            步骤按从上到下的顺序执行。“执行后等待”模拟用户在两次操作之间的停顿（think time）。同一个接口可以出现多次。
          </div>
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
  </div>
</template>

<style scoped>
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
</style>
