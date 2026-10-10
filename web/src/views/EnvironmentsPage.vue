<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormItemRule, type FormRules } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { environmentsApi, type EnvType, type Environment, type EnvironmentInput } from '../api'
import { useResourceList } from '../composables/useResourceList'
import { showError } from '../utils/feedback'
import { ENV_TYPE_OPTIONS, formatLimit } from '../utils/env'
import { fromRows, toRows, type KvRow } from '../utils/kv'
import EnvTypeTag from '../components/EnvTypeTag.vue'
import KeyValueEditor from '../components/KeyValueEditor.vue'
import VariablesTable from '../components/debug/VariablesTable.vue'

const { items, loading, load, remove } = useResourceList(environmentsApi, '被测环境')

type LimitField = 'maxVus' | 'maxRate' | 'maxDurationSec'
const LIMIT_FIELDS: LimitField[] = ['maxVus', 'maxRate', 'maxDurationSec']

interface FormState {
  name: string
  /** 新建时不预选，必须明确选一个类型 */
  type: EnvType | undefined
  baseUrl: string
  headers: KvRow[]
  variables: Record<string, string>
  // 安全上限：留空表示不限制（生产环境必填）
  maxVus: number | undefined
  maxRate: number | undefined
  maxDurationSec: number | undefined
  note: string
}

function emptyForm(): FormState {
  return {
    name: '',
    type: undefined,
    baseUrl: '',
    headers: [],
    variables: {},
    maxVus: undefined,
    maxRate: undefined,
    maxDurationSec: undefined,
    note: '',
  }
}

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormState>(emptyForm())

const isProd = computed(() => form.type === 'prod')

/** 安全上限：生产环境必填；其他类型可以留空，填了就必须大于 0。 */
function limitRule(label: string): FormItemRule[] {
  return [
    {
      trigger: 'blur',
      validator: (_rule, value: number | null | undefined, callback) => {
        if (value === null || value === undefined) {
          callback(isProd.value ? new Error(`生产环境必须填写${label}`) : undefined)
        } else if (value <= 0) {
          callback(new Error(`${label}必须大于 0`))
        } else {
          callback()
        }
      },
    },
  ]
}

const rules: FormRules<FormState> = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
  type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  baseUrl: [
    { required: true, message: '请填写基础地址', trigger: 'blur' },
    { pattern: /^https?:\/\/\S+$/i, message: '必须是 http:// 或 https:// 开头的地址', trigger: 'blur' },
  ],
  maxVus: limitRule('最大并发'),
  maxRate: limitRule('最大到达率'),
  maxDurationSec: limitRule('最长时长'),
}

function onTypeChange(): void {
  // 类型变了，上限是否必填也跟着变，清掉旧的校验提示
  formRef.value?.clearValidate(LIMIT_FIELDS)
}

function openCreate(): void {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(row: Environment): void {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    type: row.type ?? undefined,
    baseUrl: row.baseUrl,
    headers: toRows(row.headers),
    variables: { ...(row.variables ?? {}) },
    maxVus: row.maxVus ?? undefined,
    maxRate: row.maxRate ?? undefined,
    maxDurationSec: row.maxDurationSec ?? undefined,
    note: row.note ?? '',
  } satisfies FormState)
  dialogVisible.value = true
}

async function save(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid || !form.type) return
  const input: EnvironmentInput = {
    name: form.name.trim(),
    type: form.type,
    // 去掉末尾的斜杠，接口的 path 以 / 开头，直接拼在后面
    baseUrl: form.baseUrl.trim().replace(/\/+$/, ''),
    headers: fromRows(form.headers),
    variables: { ...form.variables },
    maxVus: form.maxVus ?? null,
    maxRate: form.maxRate ?? null,
    maxDurationSec: form.maxDurationSec ?? null,
    note: form.note,
  }
  saving.value = true
  try {
    if (editingId.value === null) await environmentsApi.create(input)
    else await environmentsApi.update(editingId.value, input)
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
    <div class="panel">
      <el-table v-loading="loading" :data="items" empty-text="暂无数据">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="类型" width="80">
          <template #default="{ row }"><EnvTypeTag :type="row.type" /></template>
        </el-table-column>
        <el-table-column label="基础地址" min-width="220">
          <template #default="{ row }">
            <span class="mono">{{ row.baseUrl }}</span>
          </template>
        </el-table-column>
        <el-table-column label="安全上限" align="center">
          <el-table-column label="最大并发" width="100" align="right">
            <template #default="{ row }">
              <span :class="{ muted: row.maxVus == null }">{{ formatLimit(row.maxVus) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="最大到达率" width="120" align="right">
            <template #default="{ row }">
              <span v-if="row.maxRate == null" class="muted">不限制</span>
              <template v-else>每秒 {{ row.maxRate }} 次</template>
            </template>
          </el-table-column>
          <el-table-column label="最长时长" width="100" align="right">
            <template #default="{ row }">
              <span :class="{ muted: row.maxDurationSec == null }">{{ formatLimit(row.maxDurationSec, '秒') }}</span>
            </template>
          </el-table-column>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="130" fixed="right">
          <template #header>
            <el-button link type="primary" :icon="Plus" @click="openCreate">新建</el-button>
          </template>
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row as Environment)">编辑</el-button>
            <el-button link type="danger" @click="remove(row as Environment)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建被测环境' : '编辑被测环境'"
      width="900px"
      top="6vh"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="130px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：订单系统 · 测试环境" />
        </el-form-item>
        <el-form-item label="类型" prop="type">
          <el-select v-model="form.type" placeholder="选择类型" style="width: 220px" @change="onTypeChange">
            <el-option v-for="t in ENV_TYPE_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="基础地址" prop="baseUrl">
          <el-input v-model="form.baseUrl" placeholder="https://www.example.com" />
        </el-form-item>
        <el-form-item label="公共请求头">
          <KeyValueEditor
            v-model="form.headers"
            key-placeholder="请求头名称，如 User-Agent"
            value-placeholder="值"
            add-text="添加请求头"
          />
        </el-form-item>
        <el-form-item label="环境变量">
          <VariablesTable v-model:initial="form.variables" :env-id="editingId" />
        </el-form-item>

        <fieldset class="limit-group" :class="{ 'is-prod': isProd }">
          <legend>安全上限</legend>
          <p v-if="isProd" class="limit-desc">生产环境三项必填</p>
          <el-form-item label="最大并发" prop="maxVus" :required="isProd">
            <el-input-number
              v-model="form.maxVus"
              :min="1"
              :step="1"
              :precision="0"
              controls-position="right"
              :placeholder="isProd ? '必填' : '不限制'"
            />
            <span class="unit">个虚拟用户</span>
          </el-form-item>
          <el-form-item label="最大到达率" prop="maxRate" :required="isProd">
            <el-input-number
              v-model="form.maxRate"
              :min="0"
              :step="1"
              controls-position="right"
              :placeholder="isProd ? '必填' : '不限制'"
            />
            <span class="unit">次迭代 / 秒</span>
          </el-form-item>
          <el-form-item label="最长时长" prop="maxDurationSec" :required="isProd">
            <el-input-number
              v-model="form.maxDurationSec"
              :min="1"
              :step="10"
              :precision="0"
              controls-position="right"
              :placeholder="isProd ? '必填' : '不限制'"
            />
            <span class="unit">秒</span>
          </el-form-item>
        </fieldset>

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
.limit-group {
  margin: 4px 0 18px;
  padding: 4px 16px 0;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}
.limit-group.is-prod {
  border-color: var(--el-color-danger-light-5);
}
.limit-group legend {
  padding: 0 8px;
  font-size: 14px;
  font-weight: 600;
}
.limit-desc {
  margin: 4px 0 12px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.7;
}
.limit-desc + .limit-desc {
  margin-top: -6px;
  color: var(--ink-muted);
}
</style>
