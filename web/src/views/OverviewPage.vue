<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { overviewApi, type Overview } from '../api'
import { showError } from '../utils/feedback'
import { formatCount, formatMs, formatPercent, formatTime } from '../utils/format'
import { VERDICTS, VERDICT_ORDER } from '../utils/verdict'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import VerdictTag from '../components/VerdictTag.vue'

const router = useRouter()
const data = ref<Overview | null>(null)
const loading = ref(false)

let refreshTimer: number | undefined
let disposed = false

async function load(silent = false): Promise<void> {
  window.clearTimeout(refreshTimer)
  if (!silent) loading.value = true
  try {
    data.value = await overviewApi.get()
  } catch (e) {
    if (!silent) showError(e, '加载概览失败')
  } finally {
    loading.value = false
  }
  // 有运行在进行时定时刷新，结束后数字和列表会自己更新
  if (!disposed && data.value?.runningRunId) {
    refreshTimer = window.setTimeout(() => void load(true), 3000)
  }
}

onMounted(() => void load())
onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(refreshTimer)
})

const countCards = computed(() => {
  const c = data.value?.counts
  return [
    { label: '环境', value: c?.environments, to: '/environments' },
    { label: '接口', value: c?.apis, to: '/apis' },
    { label: '业务流程', value: c?.flows, to: '/flows' },
    { label: '负载配置', value: c?.profiles, to: '/profiles' },
    { label: '测试', value: c?.tests, to: '/tests' },
    { label: '运行', value: c?.runs, to: '/runs' },
  ]
})

const verdictRows = computed(() => {
  const v = data.value?.verdicts
  const rows = VERDICT_ORDER.map((key) => ({ key, meta: VERDICTS[key], count: v?.[key] ?? 0 }))
  const total = rows.reduce((sum, r) => sum + r.count, 0)
  return { total, rows: rows.map((r) => ({ ...r, share: total > 0 ? r.count / total : 0 })) }
})
</script>

<template>
  <div v-loading="loading" class="page">
    <PageHeader title="概览" description="先维护环境、接口、业务流程、负载配置，再把它们组合成测试，然后发起运行。">
      <el-button :icon="Refresh" @click="load()">刷新</el-button>
    </PageHeader>

    <el-alert v-if="data?.runningRunId" type="info" :closable="false" show-icon class="running-alert">
      <template #title>
        有一个运行正在进行
        <el-button type="primary" size="small" class="running-go" @click="router.push(`/runs/${data.runningRunId}`)">
          查看进度
        </el-button>
      </template>
    </el-alert>

    <div class="count-grid">
      <router-link v-for="card in countCards" :key="card.to" :to="card.to" class="count-card">
        <div class="count-label">{{ card.label }}</div>
        <div class="count-value">{{ formatCount(card.value) }}</div>
      </router-link>
    </div>

    <div class="panel">
      <h2 class="panel-title">
        判定分布
        <small>已结束的运行共 {{ formatCount(verdictRows.total) }} 次</small>
      </h2>
      <template v-if="verdictRows.total > 0">
        <div class="verdict-bar" role="img" aria-label="各判定的占比">
          <template v-for="row in verdictRows.rows" :key="row.key">
            <div
              v-if="row.count > 0"
              class="verdict-seg"
              :style="{ flexGrow: row.count, background: row.meta.color }"
              :title="`${row.meta.label}：${row.count} 次（${formatPercent(row.share, 1)}）`"
            />
          </template>
        </div>
        <div class="verdict-legend">
          <div v-for="row in verdictRows.rows" :key="row.key" class="legend-item" :class="{ 'is-zero': row.count === 0 }">
            <span class="legend-swatch" :style="{ background: row.meta.color }" />
            <span>{{ row.meta.label }}</span>
            <strong class="num">{{ formatCount(row.count) }}</strong>
            <span class="muted num">{{ formatPercent(row.share, 1) }}</span>
          </div>
        </div>
      </template>
      <p v-else class="muted empty-line">还没有已结束的运行。</p>
    </div>

    <div class="panel">
      <h2 class="panel-title">
        最近的运行
        <small>最近 10 次</small>
        <router-link class="more-link" to="/runs">全部运行</router-link>
      </h2>
      <el-table :data="data?.recentRuns ?? []" empty-text="还没有运行。到“测试”页面点“运行”发起第一次。">
        <el-table-column label="开始时间" width="170">
          <template #default="{ row }">
            <router-link class="run-link num" :to="`/runs/${row.runId}`">{{ formatTime(row.startedAt) }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="testName" label="测试" min-width="160" show-overflow-tooltip />
        <el-table-column prop="profileName" label="负载配置" min-width="110" show-overflow-tooltip />
        <el-table-column prop="envName" label="环境" min-width="130" show-overflow-tooltip />
        <el-table-column label="判定" width="110">
          <template #default="{ row }">
            <StatusTag v-if="row.status === 'running'" :status="row.status" />
            <VerdictTag v-else :verdict="row.verdict" />
          </template>
        </el-table-column>
        <el-table-column label="p95" width="110" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatMs(row.summary?.p95) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="错误率" width="90" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatPercent(row.summary?.errorRate) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="请求数" width="90" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatCount(row.summary?.reqs) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.running-alert {
  margin-bottom: 16px;
}
.running-go {
  margin-left: 12px;
}

.count-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.count-card {
  padding: 14px 16px;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  background: #fff;
  color: inherit;
  text-decoration: none;
  transition: border-color 0.15s;
}
.count-card:hover {
  border-color: var(--el-color-primary);
}
.count-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.count-value {
  margin-top: 6px;
  font-size: 26px;
  font-weight: 600;
  line-height: 1.1;
}

/* 判定分布：一条按数量分段的横条，段与段之间留 2px 间隔 */
.verdict-bar {
  display: flex;
  gap: 2px;
  height: 14px;
  overflow: hidden;
  border-radius: 4px;
}
.verdict-seg {
  min-width: 4px;
}
.verdict-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 28px;
  margin-top: 12px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.legend-item.is-zero {
  opacity: 0.55;
}
.legend-swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.more-link {
  margin-left: auto;
  color: var(--el-color-primary);
  font-size: 13px;
  font-weight: 400;
  text-decoration: none;
}
.run-link {
  color: var(--el-color-primary);
  text-decoration: none;
}
.run-link:hover,
.more-link:hover {
  text-decoration: underline;
}
.empty-line {
  margin: 4px 0;
}

@media (max-width: 1100px) {
  .count-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
