<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import {
  profilesApi,
  type ConstantRateConfig,
  type ConstantVusConfig,
  type LoadModel,
  type Profile,
  type ProfileConfig,
  type ProfileInput,
  type ProfileType,
  type RampingRateConfig,
  type SharedIterationsConfig,
} from '../api'
import { useResourceList } from '../composables/useResourceList'
import { showError } from '../utils/feedback'
import {
  PROFILE_TYPE_LABELS,
  PROFILE_TYPE_OPTIONS,
  SHAPES,
  SHAPES_BY_MODEL,
  describeConfig,
  shapeOf,
  type ProfileShape,
} from '../utils/profile'
import PageHeader from '../components/PageHeader.vue'

const { items, loading, load, remove } = useResourceList(profilesApi, '负载配置')

interface StageRow {
  target: number | undefined
  durationSec: number | undefined
}
interface FormState {
  name: string
  type: ProfileType
  model: LoadModel
  shape: ProfileShape
  note: string
  // 四种形态用到的字段放在一起，保存时按形态取用
  vus: number | undefined
  iterations: number | undefined
  maxDurationSec: number | undefined
  durationSec: number | undefined
  rate: number | undefined
  preAllocatedVus: number | undefined
  startRate: number | undefined
  stages: StageRow[]
}

function emptyForm(): FormState {
  return {
    name: '',
    type: 'smoke',
    model: 'closed',
    shape: 'iterations',
    note: '',
    vus: 1,
    iterations: 10,
    maxDurationSec: 30,
    durationSec: 30,
    rate: 1,
    preAllocatedVus: 2,
    startRate: 1,
    stages: [{ target: 2, durationSec: 30 }],
  }
}

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormState>(emptyForm())

const shapeOptions = computed(() => SHAPES_BY_MODEL[form.model])

const rules: FormRules<FormState> = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
}

function selectModel(model: LoadModel): void {
  if (form.model === model) return
  form.model = model
  // 换模型后，形态回到该模型的第一种
  form.shape = SHAPES_BY_MODEL[model][0]
}

function openCreate(): void {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(row: Profile): void {
  editingId.value = row.id
  const shape = shapeOf(row.model, row.config)
  const base = emptyForm()
  const patch: Partial<FormState> = {}
  if (shape === 'iterations') {
    const c = row.config as SharedIterationsConfig
    Object.assign(patch, { vus: c.vus, iterations: c.iterations, maxDurationSec: c.maxDurationSec })
  } else if (shape === 'vus') {
    const c = row.config as ConstantVusConfig
    Object.assign(patch, { vus: c.vus, durationSec: c.durationSec })
  } else if (shape === 'rate') {
    const c = row.config as ConstantRateConfig
    Object.assign(patch, { rate: c.rate, durationSec: c.durationSec, preAllocatedVus: c.preAllocatedVus })
  } else {
    const c = row.config as RampingRateConfig
    Object.assign(patch, {
      startRate: c.startRate,
      preAllocatedVus: c.preAllocatedVus,
      stages: (c.stages ?? []).map((s) => ({ target: s.target, durationSec: s.durationSec })),
    })
  }
  Object.assign(form, base, patch, {
    name: row.name,
    type: row.type,
    model: row.model,
    shape,
    note: row.note ?? '',
  })
  dialogVisible.value = true
}

function addStage(): void {
  const last = form.stages[form.stages.length - 1]
  form.stages.push({ target: last?.target ?? form.startRate ?? 1, durationSec: 30 })
}

const isPositive = (v: number | null | undefined): v is number => typeof v === 'number' && v > 0

/** 按当前形态组装 config；字段不完整时返回错误说明。 */
function buildConfig(): ProfileConfig | string {
  switch (form.shape) {
    case 'iterations':
      if (!isPositive(form.vus)) return '请填写并发数（大于 0）'
      if (!isPositive(form.iterations)) return '请填写迭代总数（大于 0）'
      if (!isPositive(form.maxDurationSec)) return '请填写最长时长（大于 0）'
      return { vus: form.vus, iterations: form.iterations, maxDurationSec: form.maxDurationSec }
    case 'vus':
      if (!isPositive(form.vus)) return '请填写并发数（大于 0）'
      if (!isPositive(form.durationSec)) return '请填写持续时长（大于 0）'
      return { vus: form.vus, durationSec: form.durationSec }
    case 'rate':
      if (!isPositive(form.rate)) return '请填写到达率（大于 0）'
      if (!isPositive(form.durationSec)) return '请填写持续时长（大于 0）'
      if (!isPositive(form.preAllocatedVus)) return '请填写预分配并发数（大于 0）'
      return { rate: form.rate, durationSec: form.durationSec, preAllocatedVus: form.preAllocatedVus }
    case 'ramping': {
      if (typeof form.startRate !== 'number' || form.startRate < 0) return '请填写起始到达率（不小于 0）'
      if (!isPositive(form.preAllocatedVus)) return '请填写预分配并发数（大于 0）'
      if (form.stages.length === 0) return '至少需要 1 个阶段'
      const stages = []
      for (const [index, stage] of form.stages.entries()) {
        if (typeof stage.target !== 'number' || stage.target < 0) return `第 ${index + 1} 个阶段：请填写目标到达率（不小于 0）`
        if (!isPositive(stage.durationSec)) return `第 ${index + 1} 个阶段：请填写时长（大于 0）`
        stages.push({ target: stage.target, durationSec: stage.durationSec })
      }
      return { startRate: form.startRate, stages, preAllocatedVus: form.preAllocatedVus }
    }
  }
}

async function save(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  const config = buildConfig()
  if (typeof config === 'string') {
    ElMessage.warning(config)
    return
  }
  const input: ProfileInput = {
    name: form.name.trim(),
    type: form.type,
    model: form.model,
    config,
    note: form.note,
  }
  saving.value = true
  try {
    if (editingId.value === null) await profilesApi.create(input)
    else await profilesApi.update(editingId.value, input)
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
    <PageHeader>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建负载配置</el-button>
    </PageHeader>

    <div class="panel">
      <el-table v-loading="loading" :data="items" empty-text="暂无数据">
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">{{ PROFILE_TYPE_LABELS[(row as Profile).type] ?? row.type }}</template>
        </el-table-column>
        <el-table-column label="模型" width="100">
          <template #default="{ row }">
            <el-tag :type="row.model === 'open' ? 'primary' : 'info'" effect="plain" size="small">{{ row.model }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="形态" width="120">
          <template #default="{ row }">
            {{ SHAPES[shapeOf((row as Profile).model, (row as Profile).config)].label }}
          </template>
        </el-table-column>
        <el-table-column label="参数" min-width="300">
          <template #default="{ row }">{{ describeConfig((row as Profile).model, (row as Profile).config) }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row as Profile)">编辑</el-button>
            <el-button link type="danger" @click="remove(row as Profile)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建负载配置' : '编辑负载配置'"
      width="760px"
      top="6vh"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="130px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：冒烟" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 220px">
            <el-option v-for="t in PROFILE_TYPE_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>

        <el-form-item label="负载模型" required>
          <div class="model-cards">
            <div class="model-card" :class="{ 'is-active': form.model === 'closed' }" @click="selectModel('closed')">
              <el-radio :model-value="form.model" value="closed">closed · 固定并发</el-radio>
              <p>
                固定数量的虚拟用户，每个用户做完一次迭代才开始下一次。被测系统变慢时，发出的请求也会跟着变少。
              </p>
            </div>
            <div class="model-card" :class="{ 'is-active': form.model === 'open' }" @click="selectModel('open')">
              <el-radio :model-value="form.model" value="open">open · 固定到达率</el-radio>
              <p>
                按固定的速率发起新的迭代，不管上一次是否完成。被测系统变慢时压力不会减小，更接近真实流量，适合验证验收标准。
              </p>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="形态" required>
          <el-radio-group v-model="form.shape">
            <el-radio-button v-for="s in shapeOptions" :key="s" :value="s">{{ SHAPES[s].label }}</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- closed / 固定迭代数 -->
        <template v-if="form.shape === 'iterations'">
          <el-form-item label="并发数" required>
            <el-input-number v-model="form.vus" :min="1" :precision="0" controls-position="right" />
            <span class="unit">个虚拟用户</span>
          </el-form-item>
          <el-form-item label="迭代总数" required>
            <el-input-number v-model="form.iterations" :min="1" :precision="0" controls-position="right" />
            <span class="unit">次，由所有并发共同完成</span>
          </el-form-item>
          <el-form-item label="最长时长" required>
            <el-input-number v-model="form.maxDurationSec" :min="1" :precision="0" controls-position="right" />
            <span class="unit">秒，到时间没做完也会停止</span>
          </el-form-item>
        </template>

        <!-- closed / 固定并发 -->
        <template v-else-if="form.shape === 'vus'">
          <el-form-item label="并发数" required>
            <el-input-number v-model="form.vus" :min="1" :precision="0" controls-position="right" />
            <span class="unit">个虚拟用户</span>
          </el-form-item>
          <el-form-item label="持续时长" required>
            <el-input-number v-model="form.durationSec" :min="1" :precision="0" controls-position="right" />
            <span class="unit">秒</span>
          </el-form-item>
        </template>

        <!-- open / 固定到达率 -->
        <template v-else-if="form.shape === 'rate'">
          <el-form-item label="到达率" required>
            <el-input-number v-model="form.rate" :min="0" controls-position="right" />
            <span class="unit">次迭代 / 秒</span>
          </el-form-item>
          <el-form-item label="持续时长" required>
            <el-input-number v-model="form.durationSec" :min="1" :precision="0" controls-position="right" />
            <span class="unit">秒</span>
          </el-form-item>
          <el-form-item label="预分配并发数" required>
            <el-input-number v-model="form.preAllocatedVus" :min="1" :precision="0" controls-position="right" />
            <span class="unit">个虚拟用户</span>
          </el-form-item>
        </template>

        <!-- open / 阶梯到达率 -->
        <template v-else>
          <el-form-item label="起始到达率" required>
            <el-input-number v-model="form.startRate" :min="0" controls-position="right" />
            <span class="unit">次迭代 / 秒</span>
          </el-form-item>
          <el-form-item label="阶段" required>
            <div class="row-list">
              <div class="row-item row-head">
                <span class="row-index" />
                <span style="width: 190px">目标到达率（次 / 秒）</span>
                <span style="width: 190px">用时（秒）</span>
              </div>
              <div v-for="(stage, index) in form.stages" :key="index" class="row-item">
                <span class="row-index">{{ index + 1 }}</span>
                <el-input-number v-model="stage.target" :min="0" controls-position="right" style="width: 190px" />
                <el-input-number
                  v-model="stage.durationSec"
                  :min="1"
                  :precision="0"
                  controls-position="right"
                  style="width: 190px"
                />
                <el-button
                  :icon="Delete"
                  circle
                  text
                  title="删除这个阶段"
                  :disabled="form.stages.length <= 1"
                  @click="form.stages.splice(index, 1)"
                />
              </div>
              <el-button :icon="Plus" size="small" @click="addStage">添加阶段</el-button>
            </div>
          </el-form-item>
          <el-form-item label="预分配并发数" required>
            <el-input-number v-model="form.preAllocatedVus" :min="1" :precision="0" controls-position="right" />
            <span class="unit">个虚拟用户</span>
          </el-form-item>
        </template>

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
.model-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
}
.model-card {
  padding: 8px 14px 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  cursor: pointer;
}
.model-card.is-active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.model-card p {
  margin: 0;
  color: var(--el-text-color-regular);
  font-size: 12.5px;
  line-height: 1.7;
}
</style>
