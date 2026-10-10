<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Download, Loading, RefreshRight, TopRight, VideoPause } from '@element-plus/icons-vue'
import { ApiError, environmentsApi, runsApi, type Run } from '../api'
import type { StartEnv } from '../composables/useStartRun'
import { useStartRun } from '../composables/useStartRun'
import { confirmAction, errorMessage, showError } from '../utils/feedback'
import {
  DASH,
  elapsedMs,
  formatBytes,
  formatCount,
  formatDuration,
  formatMs,
  formatNumber,
  formatPercent,
  formatTime,
} from '../utils/format'
import { envTypeLabel } from '../utils/env'
import { MODEL_LABELS, demandOf, describeConfig } from '../utils/profile'
import { sloItems } from '../utils/slo'
import { INIT_SEGMENT_TITLE } from '../utils/test-data'
import { VERDICTS } from '../utils/verdict'
import EnvTypeTag from '../components/EnvTypeTag.vue'
import StepLatencyChart from '../components/StepLatencyChart.vue'
import ThresholdTable from '../components/ThresholdTable.vue'

const props = defineProps<{ runId: string }>()
const router = useRouter()
const { starting, start } = useStartRun()

const POLL_INTERVAL_MS = 2000

const run = ref<Run | null>(null)
const loading = ref(true)
const loadError = ref<string | null>(null)
const now = ref(Date.now())
const noteDraft = ref('')
const savingNote = ref(false)
const stopSending = ref(false)
const logTail = ref<string | null>(null)

let pollTimer: number | undefined
let tickTimer: number | undefined
let disposed = false

async function fetchRun(initial = false): Promise<void> {
  try {
    const data = await runsApi.get(props.runId)
    if (disposed) return
    const wasRunning = run.value?.status === 'running'
    run.value = data
    if (initial) noteDraft.value = data.note ?? ''
    if (data.status === 'finished' && (initial || wasRunning)) onFinished(data)
  } catch (e) {
    if (disposed) return
    // 首次加载失败或记录已不存在：显示错误并停止。轮询中的偶发失败忽略，下一轮再试。
    if (initial || (e instanceof ApiError && e.status === 404)) {
      loadError.value = errorMessage(e)
      run.value = null
      return
    }
  } finally {
    loading.value = false
  }
  if (!disposed && run.value?.status === 'running') {
    pollTimer = window.setTimeout(() => void fetchRun(), POLL_INTERVAL_MS)
  }
}

/** 运行结束后（或打开一个已结束的运行）做一次的事。 */
function onFinished(data: Run): void {
  // k6 没有产出指标时，把 k6 日志的末尾直接显示出来，方便定位原因
  if (!data.record?.metrics && (data.artifacts ?? []).includes('k6.log')) {
    runsApi
      .artifactText(data.runId, 'k6.log')
      .then((text) => {
        if (!disposed) logTail.value = text.trimEnd().split('\n').slice(-60).join('\n')
      })
      .catch(() => undefined)
  }
}

/** stop / PATCH 返回完整的运行对象；万一不是，就重新拉取一次。 */
function applyRun(data: Run | null | undefined): void {
  if (data && typeof data === 'object' && data.runId) run.value = data
  else void reload()
}

async function reload(): Promise<void> {
  window.clearTimeout(pollTimer)
  await fetchRun()
}

onMounted(() => {
  void fetchRun(true)
  tickTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(pollTimer)
  window.clearInterval(tickTimer)
})

const isRunning = computed(() => run.value?.status === 'running')
/** 已经请求停止、k6 还没退出 */
const stopping = computed(() => isRunning.value && (stopSending.value || run.value?.stopRequested === true))
const verdictMeta = computed(() => (run.value?.verdict ? VERDICTS[run.value.verdict] : null))
const record = computed(() => run.value?.record ?? null)
const artifacts = computed(() => run.value?.artifacts ?? [])

const validityThresholds = computed(() => (record.value?.thresholds ?? []).filter((t) => t.kind === 'validity'))
const sloThresholds = computed(() => (record.value?.thresholds ?? []).filter((t) => t.kind === 'slo'))
/** k6 没有产出记录时，后端生成的 record 里 metrics 为 null */
const hasMetrics = computed(() => !!record.value?.metrics)
const overall = computed(() => record.value?.metrics?.overall ?? null)
/** 旧的记录没有 scope，按 all */
const overallScope = computed(() => overall.value?.scope ?? 'all')
const steps = computed(() => record.value?.metrics?.steps ?? [])
// 至少有一个步骤有样本才画图；没有样本的步骤在图上留空
const chartable = computed(() => steps.value.some((s) => s.p50 !== null || s.p95 !== null || s.p99 !== null))
const multiFlow = computed(() => new Set(steps.value.map((s) => s.flowKey)).size > 1)

const pct = (value: number | null | undefined): string =>
  value === null || value === undefined ? DASH : `${formatNumber(value, 1)}%`

/** 运行期间对执行机的采样（record.executor）。旧的运行记录没有，返回 null */
const executorStats = computed(() => {
  const x = record.value?.executor
  if (!x) return null
  return [
    { label: '主机', value: x.host ?? DASH, text: true },
    { label: 'CPU 核数', value: x.cpuCores === null || x.cpuCores === undefined ? DASH : `${x.cpuCores} 核`, text: false },
    { label: 'CPU 平均占用', value: pct(x.cpuAvgPct) },
    { label: 'CPU 峰值占用', value: pct(x.cpuMaxPct) },
    { label: '内存峰值占用', value: pct(x.memMaxPct) },
    { label: '采样次数', value: formatCount(x.samples) },
  ]
})

const elapsed = computed(() => (run.value ? elapsedMs(run.value.startedAt, run.value.endedAt, now.value) : 0))

function formatClock(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** 负载配置里的计划时长（秒），用于运行中的进度提示 */
const plannedSec = computed(() => {
  const profile = run.value?.snapshot?.profile
  if (!profile?.config) return null
  const sec = demandOf(profile.model, profile.config).durationSec
  return Number.isFinite(sec) && sec > 0 ? sec : null
})
const progress = computed(() => {
  if (!plannedSec.value) return 0
  return Math.min(99, Math.round((elapsed.value / (plannedSec.value * 1000)) * 100))
})

const overallGroups = computed(() => {
  const m = overall.value
  if (!m) return []
  return [
    {
      title: '流量',
      items: [
        { label: '请求数', value: formatCount(m.reqs) },
        { label: '每秒请求数', value: formatNumber(m.rps, 2) },
        { label: '迭代数', value: formatCount(m.iterations) },
        { label: '丢弃的迭代', value: formatCount(m.droppedIterations), warn: m.droppedIterations > 0 },
        { label: '最大并发', value: formatCount(m.vusMax) },
        { label: '测试时长', value: formatDuration(record.value?.testDurationMs) },
      ],
    },
    {
      title: '响应时间',
      items: [
        { label: '平均', value: formatMs(m.avg) },
        { label: 'p50', value: formatMs(m.p50) },
        { label: 'p90', value: formatMs(m.p90) },
        { label: 'p95', value: formatMs(m.p95) },
        { label: 'p99', value: formatMs(m.p99) },
        { label: '最大', value: formatMs(m.max) },
      ],
    },
    {
      title: '质量与数据量',
      items: [
        { label: '错误率', value: formatPercent(m.errorRate), warn: m.errorRate !== null && m.errorRate > 0 },
        { label: '检查通过率', value: formatPercent(m.checksRate), warn: m.checksRate !== null && m.checksRate < 1 },
        { label: '接收数据', value: formatBytes(m.dataReceived) },
        { label: '发送数据', value: formatBytes(m.dataSent) },
      ],
    },
  ]
})

// 只嵌入运行结束后导出的静态报告。不嵌入也不链接 k6 的实时仪表盘（5665 端口）：
// 只要有浏览器连着它，k6 跑完后就不会退出，运行会一直停在“运行中”。

const hasReport = computed(() => artifacts.value.includes('dashboard.html'))
const reportUrl = computed(() => (run.value ? runsApi.artifactUrl(run.value.runId, 'dashboard.html') : ''))

const artifactLinks = computed(() =>
  artifacts.value.map((name) => ({
    name,
    url: runsApi.artifactUrl(props.runId, name),
    downloadUrl: runsApi.artifactUrl(props.runId, name, true),
  })),
)

const snapshot = computed(() => run.value?.snapshot ?? null)
const snapshotJson = computed(() => (snapshot.value ? JSON.stringify(snapshot.value, null, 2) : ''))
const snapshotOpen = ref<string[]>([])

async function stopRun(): Promise<void> {
  if (!run.value) return
  const ok = await confirmAction('确定停止这次运行吗？停止后判定为“已中止”。', '停止运行')
  if (!ok) return
  stopSending.value = true
  try {
    await runsApi.stop(run.value.runId)
    ElMessage.success('已发出停止信号，等待 k6 退出')
  } catch (e) {
    showError(e, '停止失败')
  } finally {
    stopSending.value = false
  }
  // 立刻刷新一次，拿到 stopRequested；也可能已经结束
  await reload()
}

async function saveNote(): Promise<void> {
  if (!run.value) return
  savingNote.value = true
  try {
    const note = noteDraft.value
    applyRun(await runsApi.patch(run.value.runId, { note }))
    ElMessage.success('备注已保存')
  } catch (e) {
    showError(e, '保存备注失败')
  } finally {
    savingNote.value = false
  }
}

async function toggleArchive(): Promise<void> {
  if (!run.value) return
  const next = !run.value.archived
  try {
    applyRun(await runsApi.patch(run.value.runId, { archived: next }))
    ElMessage.success(next ? '已存档' : '已取消存档')
  } catch (e) {
    showError(e)
  }
}

const deleteDisabledReason = computed(() => {
  if (isRunning.value) return '运行中不能删除'
  if (run.value?.archived) return '已存档的运行不能删除，请先取消存档'
  return ''
})

async function removeRun(): Promise<void> {
  if (!run.value) return
  const ok = await confirmAction('确定删除这次运行吗？运行记录和产物文件都会被删除，不能恢复。', '删除运行', true)
  if (!ok) return
  try {
    await runsApi.remove(run.value.runId)
    ElMessage.success('已删除')
    await router.push('/runs')
  } catch (e) {
    showError(e, '删除失败')
  }
}

async function rerun(): Promise<void> {
  const r = run.value
  if (!r) return
  if (r.testId === null || r.profileId === null || r.envId === null) {
    ElMessage.warning('这次运行用到的测试、负载配置或被测环境已经被删除，无法再次运行')
    return
  }
  const ok = await confirmAction(
    `用同样的测试「${r.testName}」、负载配置「${r.profileName}」、被测环境「${r.envName}」再运行一次？如果这些定义在上次运行后被修改过，会按现在的内容执行。`,
    '再次运行',
  )
  if (!ok) return
  // 按被测环境现在的类型决定要不要二次确认（类型可能在上次运行后改过）。
  // 取不到时用上次运行记下的类型和地址；环境已被删除的情况由后端预检拒绝。
  let env: StartEnv | null = null
  try {
    env = await environmentsApi.get(r.envId)
  } catch {
    env = r.envType ? { name: r.envName, baseUrl: r.snapshot?.env?.baseUrl ?? '', type: r.envType } : null
  }
  await start(
    {
      testId: r.testId,
      profileId: r.profileId,
      envId: r.envId,
      ...(typeof r.executorId === 'number' ? { executorId: r.executorId } : {}),
      note: '',
    },
    { env },
  )
}
</script>

<template>
  <div v-loading="loading" class="page">
    <el-result v-if="loadError" icon="error" title="无法加载这次运行" :sub-title="loadError">
      <template #extra>
        <el-button type="primary" @click="router.push('/runs')">返回运行列表</el-button>
      </template>
    </el-result>

    <template v-else-if="run">
      <div class="page-header">
        <div>
          <router-link class="back-link" to="/runs">
            <el-icon><ArrowLeft /></el-icon>运行列表
          </router-link>
          <h1 class="page-title">
            {{ run.testName }}
            <el-tag v-if="run.archived" type="warning" effect="plain" size="small" class="title-tag">已存档</el-tag>
          </h1>
          <p class="page-desc mono">{{ run.runId }}</p>
        </div>
        <div class="page-actions">
          <el-button v-if="isRunning" type="danger" :icon="VideoPause" :disabled="stopping" @click="stopRun">
            {{ stopping ? '正在停止…' : '停止' }}
          </el-button>
          <el-button v-else type="primary" plain :icon="RefreshRight" :loading="starting" @click="rerun">再次运行</el-button>
          <el-button @click="toggleArchive">{{ run.archived ? '取消存档' : '存档' }}</el-button>
          <el-tooltip :content="deleteDisabledReason" :disabled="!deleteDisabledReason" placement="bottom">
            <span>
              <el-button type="danger" plain :disabled="!!deleteDisabledReason" @click="removeRun">删除</el-button>
            </span>
          </el-tooltip>
        </div>
      </div>

      <div class="note-bar">
        <span class="muted">备注</span>
        <el-input v-model="noteDraft" placeholder="给这次运行加一句说明" maxlength="200" @keyup.enter="saveNote" />
        <el-button :disabled="noteDraft === (run.note ?? '')" :loading="savingNote" @click="saveNote">保存备注</el-button>
      </div>

      <template v-if="isRunning">
        <div class="running-banner">
          <div class="running-main">
            <el-icon class="is-loading" :size="28"><Loading /></el-icon>
            <div>
              <div class="running-title">{{ stopping ? '正在停止…' : '运行中' }}</div>
              <div class="running-sub">
                {{ stopping ? '已发出停止信号，等待 k6 退出。' : '每 2 秒自动刷新状态，结束后这里会显示判定和指标。' }}
              </div>
            </div>
          </div>
          <div class="running-clock">
            <div class="clock num">{{ formatClock(elapsed) }}</div>
            <div class="running-sub">
              已用时间<template v-if="plannedSec"> · 计划最长 {{ plannedSec }} 秒</template>
            </div>
          </div>
        </div>
        <el-progress v-if="plannedSec" :percentage="progress" :show-text="false" :stroke-width="4" class="running-progress" />

        <div class="panel">
          <h2 class="panel-title">
            k6 进度
          </h2>
          <pre v-if="run.progress" class="code-block progress-line">{{ run.progress }}</pre>
          <p v-else class="muted empty-line">{{ stopping ? '已发出停止信号，等待 k6 退出…' : '等待 k6 输出进度…' }}</p>
          <dl class="meta-grid progress-meta">
            <div><dt>测试</dt><dd>{{ run.testName }}</dd></div>
            <div><dt>负载配置</dt><dd>{{ run.profileName }}</dd></div>
            <div>
              <dt>被测环境</dt>
              <dd>{{ run.envName }} <EnvTypeTag :type="run.envType" /></dd>
            </div>
            <div v-if="run.executorName"><dt>执行机</dt><dd>{{ run.executorName }}</dd></div>
            <div><dt>开始时间</dt><dd class="num">{{ formatTime(run.startedAt) }}</dd></div>
          </dl>
        </div>
      </template>

      <template v-else>
        <div class="verdict-banner" :style="{ background: verdictMeta?.color ?? '#6b7280' }">
          <div class="verdict-main">
            <div class="verdict-caption">判定</div>
            <div class="verdict-label">{{ verdictMeta?.label ?? '未知' }}</div>
            <div v-if="record?.verdictReason" class="verdict-reason">原因：{{ record.verdictReason }}</div>
          </div>
          <dl class="verdict-meta">
            <div><dt>负载配置</dt><dd>{{ run.profileName }}</dd></div>
            <div>
              <dt>被测环境</dt>
              <dd>
                {{ run.envName }}
                <span v-if="run.envType" class="banner-pill">{{ envTypeLabel(run.envType) }}</span>
              </dd>
            </div>
            <div v-if="run.executorName"><dt>执行机</dt><dd>{{ run.executorName }}</dd></div>
            <div><dt>开始时间</dt><dd class="num">{{ formatTime(run.startedAt) }}</dd></div>
            <div><dt>用时</dt><dd class="num">{{ formatDuration(elapsedMs(run.startedAt, run.endedAt)) }}</dd></div>
            <div><dt>k6 退出码</dt><dd class="num">{{ run.exitCode ?? DASH }}</dd></div>
            <div v-if="record?.fingerprint"><dt>k6 版本</dt><dd>{{ record.fingerprint.k6Version }}</dd></div>
          </dl>
        </div>

        <!-- k6 没有产出指标：2~6 无从显示，给出原因和日志 -->
        <div v-if="!hasMetrics" class="panel">
          <h2 class="panel-title">没有指标数据</h2>
          <p class="muted no-record">
            k6 没有产出可用的运行记录，所以没有有效性检查、验收标准和指标可以显示。原因通常能在 k6 的输出日志里找到。
          </p>
          <template v-if="logTail !== null">
            <div class="log-caption muted">k6.log（最后 60 行）</div>
            <pre class="code-block">{{ logTail || '（日志为空）' }}</pre>
          </template>
        </div>

        <div v-if="hasMetrics" class="panel">
          <h2 class="panel-title">
            有效性检查
          </h2>
          <ThresholdTable v-if="validityThresholds.length" :thresholds="validityThresholds" />
          <p v-else class="muted empty-line">这次运行没有有效性检查项。</p>
        </div>

        <!-- 执行机在运行期间的资源占用。旧的运行记录没有这一项，不显示 -->
        <div v-if="executorStats" class="panel">
          <h2 class="panel-title">执行机 <small>不参与判定</small></h2>
          <div class="stat-grid">
            <div v-for="item in executorStats" :key="item.label" class="stat">
              <div class="stat-label">{{ item.label }}</div>
              <div class="stat-value" :class="{ 'is-text': item.text }">{{ item.value }}</div>
            </div>
          </div>
        </div>

        <template v-if="hasMetrics">
          <div class="panel">
            <h2 class="panel-title">
              验收标准
            </h2>
            <el-alert
              v-if="run.verdict === 'invalid'"
              type="warning"
              :closable="false"
              show-icon
              title="测试无效，以下结果不作为结论"
              class="void-alert"
            />
            <div :class="{ 'is-void': run.verdict === 'invalid' }">
              <ThresholdTable v-if="sloThresholds.length" :thresholds="sloThresholds" />
              <p v-else class="muted empty-line">这个测试没有设置验收标准。</p>
            </div>
          </div>

          <div class="panel">
            <h2 class="panel-title">
              总体指标
              <el-tag
                v-if="overallScope === 'main'"
                size="small"
                effect="plain"
                title="不含初始化段的请求"
                disable-transitions
              >
                业务请求
              </el-tag>
            </h2>
            <template v-if="overall">
              <div v-for="group in overallGroups" :key="group.title" class="stat-group">
                <div class="stat-group-title">{{ group.title }}</div>
                <div class="stat-grid">
                  <div v-for="item in group.items" :key="item.label" class="stat" :class="{ 'is-warn': item.warn }">
                    <div class="stat-label">{{ item.label }}</div>
                    <div class="stat-value">{{ item.value }}</div>
                  </div>
                </div>
              </div>
            </template>
            <p v-else class="muted empty-line">运行记录里没有总体指标。</p>
          </div>

          <div class="panel">
            <h2 class="panel-title">
              分步骤指标
            </h2>
            <el-table :data="steps" size="small" empty-text="运行记录里没有分步骤指标">
              <el-table-column v-if="multiFlow" prop="flowName" label="业务流程" min-width="140" />
              <el-table-column label="步骤" min-width="180">
                <template #default="{ row }">
                  <el-tag
                    v-if="row.phase === 'init'"
                    type="warning"
                    size="small"
                    effect="plain"
                    class="phase-tag"
                    :title="INIT_SEGMENT_TITLE"
                    disable-transitions
                  >
                    初始化
                  </el-tag>
                  {{ row.stepName }} <span class="muted mono">{{ row.stepKey }}</span>
                  <el-tag v-if="row.count === 0" type="info" size="small" effect="plain" class="no-sample">没有发出请求</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="请求数" width="100" align="right">
                <template #default="{ row }"><span class="num">{{ formatCount(row.count) }}</span></template>
              </el-table-column>
              <el-table-column label="平均" width="100" align="right">
                <template #default="{ row }"><span class="num">{{ formatNumber(row.avg) }}</span></template>
              </el-table-column>
              <el-table-column label="p50" width="100" align="right">
                <template #default="{ row }"><span class="num">{{ formatNumber(row.p50) }}</span></template>
              </el-table-column>
              <el-table-column label="p95" width="100" align="right">
                <template #default="{ row }"><span class="num">{{ formatNumber(row.p95) }}</span></template>
              </el-table-column>
              <el-table-column label="p99" width="100" align="right">
                <template #default="{ row }"><span class="num">{{ formatNumber(row.p99) }}</span></template>
              </el-table-column>
              <el-table-column label="最大" width="100" align="right">
                <template #default="{ row }"><span class="num">{{ formatNumber(row.max) }}</span></template>
              </el-table-column>
              <el-table-column label="错误率" width="100" align="right">
                <template #default="{ row }">
                  <span class="num" :class="{ 'cell-warn': row.errorRate > 0 }">{{ formatPercent(row.errorRate) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="panel">
            <h2 class="panel-title">
              分步骤响应时间
            </h2>
            <StepLatencyChart v-if="chartable" :steps="steps" />
            <p v-else class="muted empty-line">没有分步骤数据可以画图。</p>
          </div>
        </template>

        <div v-if="hasReport" class="panel">
          <h2 class="panel-title">
            k6 图表
            <span class="panel-tools">
              <a class="open-link" :href="reportUrl" target="_blank" rel="noopener">
                新窗口打开<el-icon><TopRight /></el-icon>
              </a>
            </span>
          </h2>
          <iframe class="k6-frame" :src="reportUrl" title="k6 图表报告" loading="lazy" />
        </div>

        <div class="panel">
          <h2 class="panel-title">产物</h2>
          <ul v-if="artifactLinks.length" class="artifact-list">
            <li v-for="item in artifactLinks" :key="item.name">
              <a class="open-link mono" :href="item.url" target="_blank" rel="noopener">{{ item.name }}</a>
              <a class="open-link" :href="item.downloadUrl">
                <el-icon><Download /></el-icon>下载
              </a>
            </li>
          </ul>
          <p v-else class="muted empty-line">没有产物文件。</p>
        </div>
      </template>

      <div class="panel">
        <h2 class="panel-title">
          运行时的配置快照
        </h2>
        <template v-if="snapshot">
          <dl class="meta-grid snapshot-summary">
            <div>
              <dt>被测环境</dt>
              <dd>
                <EnvTypeTag :type="snapshot.env?.type" />
                <span class="mono">{{ snapshot.env?.baseUrl ?? DASH }}</span>
              </dd>
            </div>
            <div v-if="snapshot.profile?.config">
              <dt>负载</dt>
              <dd>
                {{ MODEL_LABELS[snapshot.profile.model] }}：{{ describeConfig(snapshot.profile.model, snapshot.profile.config) }}
              </dd>
            </div>
            <div>
              <dt>验收标准</dt>
              <dd>{{ sloItems(snapshot.slo).join('；') || '未设置' }}</dd>
            </div>
          </dl>
          <el-collapse v-model="snapshotOpen">
            <el-collapse-item title="展开查看完整快照（JSON）" name="json">
              <pre class="code-block">{{ snapshotJson }}</pre>
            </el-collapse-item>
          </el-collapse>
        </template>
        <p v-else class="muted empty-line">没有配置快照。</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
  color: var(--ink-muted);
  font-size: 13px;
  text-decoration: none;
}
.back-link:hover {
  color: var(--el-color-primary);
}
.title-tag {
  margin-left: 8px;
  vertical-align: middle;
}

.note-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.note-bar > span {
  flex-shrink: 0;
}

/* ---------- 运行中 ---------- */
.running-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 20px 24px;
  border-radius: 8px 8px 0 0;
  background: #1f4f8f;
  color: #fff;
}
.running-main {
  display: flex;
  align-items: center;
  gap: 14px;
}
.running-title {
  font-size: 22px;
  font-weight: 600;
}
.running-sub {
  margin-top: 4px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 13px;
}
.running-clock {
  text-align: right;
}
.clock {
  font-size: 32px;
  font-weight: 600;
  line-height: 1;
}
.running-progress {
  margin-bottom: 16px;
}
.running-progress :deep(.el-progress-bar__outer) {
  border-radius: 0 0 8px 8px;
}
.running-progress :deep(.el-progress-bar__inner) {
  border-radius: 0;
}
.running-banner:not(:has(+ .running-progress)) {
  margin-bottom: 16px;
  border-radius: 8px;
}

/* ---------- 判定横幅 ---------- */
.verdict-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 32px;
  margin-bottom: 16px;
  padding: 22px 26px;
  border-radius: 8px;
  color: #fff;
}
.verdict-caption {
  font-size: 12px;
  letter-spacing: 2px;
  opacity: 0.8;
}
.verdict-label {
  margin: 2px 0 6px;
  font-size: 34px;
  font-weight: 700;
  line-height: 1.2;
}
.verdict-desc {
  max-width: 460px;
  font-size: 13.5px;
  line-height: 1.6;
  opacity: 0.95;
}
.verdict-reason {
  display: inline-block;
  margin-top: 10px;
  padding: 4px 10px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.18);
  font-size: 13px;
}
.banner-pill {
  display: inline-block;
  margin-left: 4px;
  padding: 0 7px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
  vertical-align: middle;
}
.verdict-meta {
  display: grid;
  grid-template-columns: repeat(4, auto);
  gap: 14px 32px;
  margin: 0;
}
.verdict-meta dt {
  font-size: 12px;
  opacity: 0.75;
}
.verdict-meta dd {
  margin: 2px 0 0;
  font-size: 14px;
  font-weight: 600;
}

/* ---------- 通用区块 ---------- */
.meta-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 40px;
  margin: 0;
}
.meta-grid dt {
  color: var(--ink-muted);
  font-size: 12px;
}
.meta-grid dd {
  margin: 2px 0 0;
}
.snapshot-summary {
  margin-bottom: 12px;
}

.panel-tools {
  display: inline-flex;
  align-items: center;
  gap: 14px;
  margin-left: auto;
  font-size: 13px;
  font-weight: 400;
}
.open-link {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.open-link:hover {
  text-decoration: underline;
}

.empty-line {
  margin: 4px 0;
}
.no-record {
  margin: 0 0 12px;
  line-height: 1.7;
}
.log-caption {
  margin-bottom: 6px;
  font-size: 12px;
}

/* 判定为 invalid 时，验收标准整体置灰 */
.void-alert {
  margin-bottom: 12px;
}
.is-void {
  filter: grayscale(1);
  opacity: 0.45;
}

/* ---------- 总体指标 ---------- */
.stat-group + .stat-group {
  margin-top: 16px;
}
.stat-group-title {
  margin-bottom: 8px;
  color: var(--ink-muted);
  font-size: 12px;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}
.stat {
  padding: 10px 12px;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  background: #fafbfc;
}
.stat-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.stat-value {
  margin-top: 4px;
  font-size: 18px;
  font-weight: 600;
}
.stat-value.is-text {
  overflow: hidden;
  font-size: 14px;
  line-height: 26px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stat.is-warn {
  border-color: #f0c78a;
  background: #fdf6ec;
}
.no-sample {
  margin-left: 6px;
}
.phase-tag {
  margin-right: 6px;
}
.cell-warn {
  color: #d03b3b;
  font-weight: 600;
}

/* ---------- k6 图表、代码块 ---------- */
.k6-frame {
  display: block;
  width: 100%;
  height: 720px;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  background: #fff;
}
.code-block {
  max-height: 480px;
  margin: 0;
  padding: 12px 14px;
  overflow: auto;
  border-radius: 6px;
  background: #f6f7f9;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre;
}

.artifact-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.artifact-list li {
  display: flex;
  align-items: baseline;
  gap: 16px;
  padding: 6px 0;
}
.artifact-list li + li {
  border-top: 1px solid var(--hairline);
}
.artifact-list a.mono {
  min-width: 170px;
}
.artifact-desc {
  flex: 1;
}
.progress-line {
  margin-bottom: 14px;
  white-space: pre-wrap;
}
.progress-meta {
  margin-bottom: 4px;
}

@media (max-width: 1100px) {
  .stat-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .verdict-banner {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
