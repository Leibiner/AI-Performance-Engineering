<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Edit, Refresh } from '@element-plus/icons-vue'
import { executorsApi, type Executor } from '../api'
import { showError } from '../utils/feedback'
import { DASH, formatNumber, formatTime } from '../utils/format'
import PageHeader from '../components/PageHeader.vue'

const REFRESH_MS = 3000

const items = ref<Executor[]>([])
const loading = ref(false)
/** 页面上这份数据的采集时间（执行机的硬件、负载等字段是每次请求时实时采集的） */
const fetchedAt = ref<string | null>(null)

let refreshTimer: number | undefined
let disposed = false

async function load(silent = false): Promise<void> {
  window.clearTimeout(refreshTimer)
  if (!silent) loading.value = true
  try {
    items.value = await executorsApi.list()
    fetchedAt.value = new Date().toISOString()
  } catch (e) {
    if (!silent) showError(e, '加载执行机失败')
  } finally {
    loading.value = false
  }
  // 有运行在进行时每隔几秒刷新一次，能看到负载和可用内存的变化，也能看到它结束
  if (!disposed && items.value.some((x) => x.status === 'running')) {
    refreshTimer = window.setTimeout(() => void load(true), REFRESH_MS)
  }
}

onMounted(() => void load())
onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(refreshTimer)
})

const KIND_LABELS: Record<string, string> = { local: '本机' }

function text(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === '' ? DASH : String(value)
}
/** MB → 「15.5 GB」 */
function mbToGb(mb: number | null | undefined): string {
  return mb === null || mb === undefined ? DASH : `${formatNumber(mb / 1024, 1)} GB`
}
function memory(x: Executor): string {
  if (x.memTotalMb === null && x.memAvailableMb === null) return DASH
  return `${mbToGb(x.memTotalMb)} / 可用 ${mbToGb(x.memAvailableMb)}`
}

interface FormState {
  name: string
  note: string
}
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormState>({ name: '', note: '' })
const rules: FormRules<FormState> = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
}

function openEdit(row: Executor): void {
  editingId.value = row.id
  form.name = row.name
  form.note = row.note ?? ''
  dialogVisible.value = true
}

async function save(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid || editingId.value === null) return
  saving.value = true
  try {
    await executorsApi.update(editingId.value, { name: form.name.trim(), note: form.note })
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load(true)
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div v-loading="loading" class="page">
    <PageHeader title="执行机">
      <el-button :icon="Refresh" @click="load()">刷新</el-button>
    </PageHeader>

    <div v-if="!loading && items.length === 0" class="panel">
      <el-empty description="暂无执行机" />
    </div>

    <div v-for="x in items" :key="x.id" class="panel">
      <div class="executor-head">
        <h2 class="executor-name">{{ x.name }}</h2>
        <el-tag v-if="x.status === 'running'" type="primary" effect="dark" round>运行中</el-tag>
        <el-tag v-else type="success" effect="plain" round>空闲</el-tag>
        <router-link v-if="x.status === 'running' && x.runningRunId" class="run-link" :to="`/runs/${x.runningRunId}`">
          查看正在进行的运行
        </router-link>
        <span class="executor-tools">
          <span v-if="fetchedAt" class="muted num">数据采集于 {{ formatTime(fetchedAt) }}</span>
          <el-button :icon="Edit" size="small" @click="openEdit(x)">编辑名称和备注</el-button>
        </span>
      </div>

      <el-descriptions title="基本信息" :column="3" border class="group">
        <el-descriptions-item label="名称">{{ text(x.name) }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ KIND_LABELS[x.kind] ?? text(x.kind) }}</el-descriptions-item>
        <el-descriptions-item label="主机名">
          <span class="mono">{{ text(x.host) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="IP">
          <span class="mono">{{ text(x.ip) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="备注" :span="2">{{ text(x.note) }}</el-descriptions-item>
      </el-descriptions>

      <el-descriptions title="硬件与系统" :column="3" border class="group">
        <el-descriptions-item label="系统">{{ text(x.os) }}</el-descriptions-item>
        <el-descriptions-item label="架构">{{ text(x.arch) }}</el-descriptions-item>
        <el-descriptions-item label="CPU 核数">
          {{ x.cpuCores === null || x.cpuCores === undefined ? DASH : `${x.cpuCores} 核` }}
        </el-descriptions-item>
        <el-descriptions-item label="内存总量 / 可用">{{ memory(x) }}</el-descriptions-item>
        <el-descriptions-item label="1 分钟负载">
          <span class="num">{{ formatNumber(x.loadAvg1, 2) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="磁盘剩余">
          {{ x.diskFreeGb === null || x.diskFreeGb === undefined ? DASH : `${formatNumber(x.diskFreeGb, 1)} GB` }}
        </el-descriptions-item>
      </el-descriptions>

      <el-descriptions title="软件" :column="3" border class="group">
        <el-descriptions-item label="k6 版本">{{ text(x.k6Version) }}</el-descriptions-item>
        <el-descriptions-item label="k6 路径" :span="2">
          <span class="mono">{{ text(x.k6Path) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="Python 版本">{{ text(x.pythonVersion) }}</el-descriptions-item>
        <el-descriptions-item label="uv 版本" :span="2">{{ text(x.uvVersion) }}</el-descriptions-item>
      </el-descriptions>

      <el-descriptions title="目录" :column="1" border class="group">
        <el-descriptions-item label="项目目录">
          <span class="mono">{{ text(x.projectDir) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="结果目录">
          <span class="mono">{{ text(x.resultsDir) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="数据目录">
          <span class="mono">{{ text(x.dataDir) }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <el-descriptions title="状态" :column="1" border class="group">
        <el-descriptions-item label="当前状态">
          <template v-if="x.status === 'running'">
            运行中
            <router-link v-if="x.runningRunId" class="run-link mono" :to="`/runs/${x.runningRunId}`">
              {{ x.runningRunId }}
            </router-link>
            <span class="muted">（每 {{ REFRESH_MS / 1000 }} 秒自动刷新）</span>
          </template>
          <template v-else>空闲，可以发起运行</template>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <el-dialog v-model="dialogVisible" title="编辑执行机" width="560px" :close-on-click-modal="false" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="3" />
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
.executor-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}
.executor-name {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.executor-tools {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
  font-size: 12px;
}
.run-link {
  margin-left: 4px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.run-link:hover {
  text-decoration: underline;
}
.group {
  margin-top: 18px;
}
.group :deep(.el-descriptions__header) {
  margin-bottom: 8px;
}
.group :deep(.el-descriptions__title) {
  font-size: 14px;
}
.group :deep(.el-descriptions__label) {
  width: 130px;
  white-space: nowrap;
}
</style>
