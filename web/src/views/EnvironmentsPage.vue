<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { environmentsApi, type Environment, type EnvironmentInput } from '../api'
import { useResourceList } from '../composables/useResourceList'
import { showError } from '../utils/feedback'
import { fromRows, toRows, type KvRow } from '../utils/kv'
import KeyValueEditor from '../components/KeyValueEditor.vue'
import PageHeader from '../components/PageHeader.vue'

const { items, loading, load, remove } = useResourceList(environmentsApi, '环境')

interface FormState {
  name: string
  baseUrl: string
  headers: KvRow[]
  maxVus: number | undefined
  maxRate: number | undefined
  maxDurationSec: number | undefined
  note: string
}

function emptyForm(): FormState {
  return { name: '', baseUrl: '', headers: [], maxVus: 1, maxRate: 1, maxDurationSec: 30, note: '' }
}

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormState>(emptyForm())

const positive = (label: string) => [
  { required: true, type: 'number' as const, min: 0.000001, message: `${label}必填，且必须大于 0`, trigger: 'blur' },
]
const rules: FormRules<FormState> = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
  baseUrl: [
    { required: true, message: '请填写基础地址', trigger: 'blur' },
    { pattern: /^https?:\/\/\S+$/i, message: '必须是 http:// 或 https:// 开头的地址', trigger: 'blur' },
  ],
  maxVus: positive('最大并发'),
  maxRate: positive('最大到达率'),
  maxDurationSec: positive('最长时长'),
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
    baseUrl: row.baseUrl,
    headers: toRows(row.headers),
    maxVus: row.maxVus,
    maxRate: row.maxRate,
    maxDurationSec: row.maxDurationSec,
    note: row.note ?? '',
  } satisfies FormState)
  dialogVisible.value = true
}

async function save(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  const input: EnvironmentInput = {
    name: form.name.trim(),
    // 去掉末尾的斜杠，接口的 path 以 / 开头，直接拼在后面
    baseUrl: form.baseUrl.trim().replace(/\/+$/, ''),
    headers: fromRows(form.headers),
    maxVus: form.maxVus as number,
    maxRate: form.maxRate as number,
    maxDurationSec: form.maxDurationSec as number,
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
    <PageHeader
      title="环境"
      description="被测系统的地址，以及这个环境允许的流量上限。发起运行时，超过上限的负载配置会被预检拒绝。"
    >
      <el-button type="primary" :icon="Plus" @click="openCreate">新建环境</el-button>
    </PageHeader>

    <div class="panel">
      <el-table v-loading="loading" :data="items" empty-text="还没有环境">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="基础地址" min-width="220">
          <template #default="{ row }">
            <span class="mono">{{ row.baseUrl }}</span>
          </template>
        </el-table-column>
        <el-table-column label="公共请求头" width="110" align="right">
          <template #default="{ row }">
            {{ Object.keys(row.headers ?? {}).length }} 个
          </template>
        </el-table-column>
        <el-table-column prop="maxVus" label="最大并发" width="100" align="right" />
        <el-table-column label="最大到达率" width="120" align="right">
          <template #default="{ row }">每秒 {{ row.maxRate }} 次</template>
        </el-table-column>
        <el-table-column label="最长时长" width="100" align="right">
          <template #default="{ row }">{{ row.maxDurationSec }} 秒</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row as Environment)">编辑</el-button>
            <el-button link type="danger" @click="remove(row as Environment)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建环境' : '编辑环境'"
      width="680px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="130px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：百度（仅冒烟）" />
        </el-form-item>
        <el-form-item label="基础地址" prop="baseUrl">
          <el-input v-model="form.baseUrl" placeholder="https://www.example.com" />
          <div class="form-hint">接口的路径会拼在这个地址后面。</div>
        </el-form-item>
        <el-form-item label="公共请求头">
          <KeyValueEditor
            v-model="form.headers"
            key-placeholder="请求头名称，如 User-Agent"
            value-placeholder="值"
            add-text="添加请求头"
          />
          <div class="form-hint">这个环境下的所有请求都会带上这些请求头。</div>
        </el-form-item>
        <el-form-item label="最大并发" prop="maxVus">
          <el-input-number v-model="form.maxVus" :min="1" :step="1" :precision="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="最大到达率" prop="maxRate">
          <el-input-number v-model="form.maxRate" :min="0" :step="1" controls-position="right" />
          <span class="unit">次迭代 / 秒</span>
        </el-form-item>
        <el-form-item label="最长时长" prop="maxDurationSec">
          <el-input-number v-model="form.maxDurationSec" :min="1" :step="10" :precision="0" controls-position="right" />
          <span class="unit">秒</span>
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
