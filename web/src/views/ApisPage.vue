<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { apisApi, type ApiDef, type ApiDefInput, type Extract, type ExtractFrom, type HttpMethod } from '../api'
import { useResourceList } from '../composables/useResourceList'
import { showError } from '../utils/feedback'
import { fromRows, toRows, type KvRow } from '../utils/kv'
import { DASH } from '../utils/format'
import KeyValueEditor from '../components/KeyValueEditor.vue'
import PageHeader from '../components/PageHeader.vue'

const { items, loading, load, remove } = useResourceList(apisApi, '接口')

const METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const METHOD_TAG: Record<HttpMethod, 'success' | 'primary' | 'warning' | 'info' | 'danger'> = {
  GET: 'success',
  POST: 'primary',
  PUT: 'warning',
  PATCH: 'info',
  DELETE: 'danger',
}

const EXTRACT_SOURCES: { value: ExtractFrom; label: string; placeholder: string }[] = [
  { value: 'json', label: 'JSON 路径', placeholder: '点号路径，如 data.items.0.id' },
  { value: 'regex', label: '正则', placeholder: '正则表达式，取第 1 个捕获组，如 token=(\\w+)' },
  { value: 'header', label: '响应头', placeholder: '响应头名称，如 Set-Cookie' },
]
function extractPlaceholder(from: ExtractFrom): string {
  return EXTRACT_SOURCES.find((s) => s.value === from)?.placeholder ?? ''
}

interface FormState {
  name: string
  method: HttpMethod
  path: string
  headers: KvRow[]
  body: string
  expectStatus: number | undefined
  expectBodyContains: string
  extracts: Extract[]
  note: string
}

function emptyForm(): FormState {
  return {
    name: '',
    method: 'GET',
    path: '/',
    headers: [],
    body: '',
    expectStatus: 200,
    expectBodyContains: '',
    extracts: [],
    note: '',
  }
}

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormState>(emptyForm())

const rules: FormRules<FormState> = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
  method: [{ required: true, message: '请选择方法', trigger: 'change' }],
  path: [
    { required: true, message: '请填写路径', trigger: 'blur' },
    { pattern: /^\//, message: '路径必须以 / 开头', trigger: 'blur' },
  ],
  expectStatus: [
    { required: true, type: 'number', min: 100, max: 599, message: '请填写 100 ~ 599 之间的状态码', trigger: 'blur' },
  ],
}

function openCreate(): void {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(row: ApiDef): void {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    method: row.method,
    path: row.path,
    headers: toRows(row.headers),
    body: row.body ?? '',
    expectStatus: row.expectStatus,
    expectBodyContains: row.expectBodyContains ?? '',
    extracts: (row.extracts ?? []).map((e) => ({ ...e })),
    note: row.note ?? '',
  } satisfies FormState)
  dialogVisible.value = true
}

function addExtract(): void {
  form.extracts.push({ var: '', from: 'json', expr: '' })
}

async function save(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  const extracts = form.extracts.map((e) => ({ var: e.var.trim(), from: e.from, expr: e.expr.trim() }))
  const badIndex = extracts.findIndex((e) => !e.var || !e.expr)
  if (badIndex >= 0) {
    ElMessage.warning(`第 ${badIndex + 1} 条变量提取没有填完整：变量名和表达式都要填`)
    return
  }
  const invalidName = extracts.find((e) => /[\s{}]/.test(e.var))
  if (invalidName) {
    ElMessage.warning(`变量名「${invalidName.var}」不能包含空格或花括号`)
    return
  }

  const input: ApiDefInput = {
    name: form.name.trim(),
    method: form.method,
    path: form.path.trim(),
    headers: fromRows(form.headers),
    body: form.body === '' ? null : form.body,
    expectStatus: form.expectStatus as number,
    expectBodyContains: form.expectBodyContains === '' ? null : form.expectBodyContains,
    extracts,
    note: form.note,
  }
  saving.value = true
  try {
    if (editingId.value === null) await apisApi.create(input)
    else await apisApi.update(editingId.value, input)
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
    <PageHeader title="接口" description="被测系统的一个请求。接口只描述“请求什么、期望什么”，顺序在业务流程里编排。">
      <el-button type="primary" :icon="Plus" @click="openCreate">新建接口</el-button>
    </PageHeader>

    <div class="panel">
      <el-table v-loading="loading" :data="items" empty-text="还没有接口">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="方法" width="90">
          <template #default="{ row }">
            <el-tag :type="METHOD_TAG[(row as ApiDef).method]" size="small" effect="plain">{{ row.method }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="路径" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono">{{ row.path }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="expectStatus" label="期望状态码" width="110" align="right" />
        <el-table-column label="期望包含的文本" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.expectBodyContains || DASH }}</template>
        </el-table-column>
        <el-table-column label="变量提取" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <template v-if="(row as ApiDef).extracts?.length">
              <span class="mono">{{ (row as ApiDef).extracts.map((e) => e.var).join('、') }}</span>
            </template>
            <span v-else class="muted">{{ DASH }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row as ApiDef)">编辑</el-button>
            <el-button link type="danger" @click="remove(row as ApiDef)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建接口' : '编辑接口'"
      width="820px"
      top="6vh"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-alert type="info" :closable="false" show-icon class="var-tip">
        <template #title>
          路径、请求头的值、请求体里可以用 <code v-pre>{{变量名}}</code>，运行时会替换成同一流程中前面步骤提取到的变量。
        </template>
      </el-alert>

      <el-form ref="formRef" :model="form" :rules="rules" label-width="130px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：百度首页" />
        </el-form-item>
        <el-form-item label="方法" prop="method">
          <el-select v-model="form.method" style="width: 140px">
            <el-option v-for="m in METHODS" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="路径" prop="path">
          <el-input v-model="form.path" placeholder="/api/orders/{{orderId}}" class="mono" />
          <div class="form-hint">以 / 开头，拼在环境的基础地址后面。</div>
        </el-form-item>
        <el-form-item label="请求头">
          <KeyValueEditor
            v-model="form.headers"
            key-placeholder="请求头名称，如 Content-Type"
            value-placeholder="值，可以用 {{变量名}}"
            add-text="添加请求头"
          />
        </el-form-item>
        <el-form-item label="请求体">
          <el-input
            v-model="form.body"
            type="textarea"
            :rows="4"
            class="mono"
            placeholder="留空表示不发送请求体。发送 JSON 时记得加请求头 Content-Type: application/json"
          />
        </el-form-item>
        <el-form-item label="期望状态码" prop="expectStatus">
          <el-input-number v-model="form.expectStatus" :min="100" :max="599" :precision="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="期望包含的文本">
          <el-input v-model="form.expectBodyContains" placeholder="留空表示不检查响应内容" />
          <div class="form-hint">状态码和文本检查不通过会计入“检查通过率”。</div>
        </el-form-item>
        <el-form-item label="变量提取">
          <div class="row-list">
            <div v-for="(item, index) in form.extracts" :key="index" class="row-item">
              <el-input v-model="item.var" placeholder="变量名" style="width: 150px" class="mono" />
              <el-select v-model="item.from" style="width: 130px">
                <el-option v-for="s in EXTRACT_SOURCES" :key="s.value" :label="s.label" :value="s.value" />
              </el-select>
              <el-input v-model="item.expr" class="grow mono" :placeholder="extractPlaceholder(item.from)" />
              <el-button :icon="Delete" circle text title="删除这一条" @click="form.extracts.splice(index, 1)" />
            </div>
            <el-button :icon="Plus" size="small" @click="addExtract">添加提取规则</el-button>
          </div>
          <div class="form-hint">
            从响应里取值存成变量，供同一流程的后续步骤用 <code v-pre>{{变量名}}</code> 引用。变量名建议只用字母、数字和下划线。
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
.var-tip {
  margin-bottom: 18px;
}
.var-tip code {
  padding: 1px 5px;
  border-radius: 3px;
  background: #fff;
}
</style>
