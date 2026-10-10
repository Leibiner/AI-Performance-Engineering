<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { runsApi, testsApi, type RunListItem, type RunStatus, type TestDef, type Verdict } from '../api'
import { confirmAction, showError } from '../utils/feedback'
import { formatCount, formatMs, formatPercent, formatTime } from '../utils/format'
import { VERDICT_OPTIONS } from '../utils/verdict'
import EnvTypeTag from '../components/EnvTypeTag.vue'
import PageHeader from '../components/PageHeader.vue'
import StatusTag from '../components/StatusTag.vue'
import VerdictTag from '../components/VerdictTag.vue'

const router = useRouter()

const items = ref<RunListItem[]>([])
const total = ref(0)
const loading = ref(false)
const tests = ref<TestDef[]>([])

interface Filters {
  testId: number | undefined
  verdict: Verdict | undefined
  status: RunStatus | undefined
  archived: boolean | undefined
}
const filters = reactive<Filters>({ testId: undefined, verdict: undefined, status: undefined, archived: undefined })
const page = ref(1)
const pageSize = ref(20)

let refreshTimer: number | undefined
let disposed = false

// 只采用最后一次请求的结果，避免连续筛选或翻页时旧响应覆盖新响应
let loadSeq = 0

async function load(silent = false): Promise<void> {
  window.clearTimeout(refreshTimer)
  const seq = ++loadSeq
  if (!silent) loading.value = true
  try {
    const result = await runsApi.list({
      // 清空选择框后值可能是 null 或空字符串，统一当作不筛选
      testId: filters.testId || undefined,
      verdict: filters.verdict || undefined,
      status: filters.status || undefined,
      archived: typeof filters.archived === 'boolean' ? filters.archived : undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    if (seq !== loadSeq) return
    items.value = result.items ?? []
    total.value = result.total ?? 0
  } catch (e) {
    if (seq !== loadSeq) return
    if (!silent) showError(e, '加载运行列表失败')
  } finally {
    if (seq === loadSeq) loading.value = false
  }
  if (seq !== loadSeq) return
  // 列表里有运行中的记录时，定时刷新直到它结束
  if (!disposed && items.value.some((r) => r.status === 'running')) {
    refreshTimer = window.setTimeout(() => void load(true), 3000)
  }
}

function onFilterChange(): void {
  page.value = 1
  void load()
}
function resetFilters(): void {
  Object.assign(filters, { testId: undefined, verdict: undefined, status: undefined, archived: undefined })
  onFilterChange()
}

async function toggleArchive(row: RunListItem): Promise<void> {
  try {
    await runsApi.patch(row.runId, { archived: !row.archived })
    ElMessage.success(row.archived ? '已取消存档' : '已存档')
    await load(true)
  } catch (e) {
    showError(e)
  }
}

async function remove(row: RunListItem): Promise<void> {
  const ok = await confirmAction(
    `确定删除 ${formatTime(row.startedAt)} 的这次运行吗？运行记录和产物文件都会被删除，不能恢复。`,
    '删除运行',
    true,
  )
  if (!ok) return
  try {
    await runsApi.remove(row.runId)
    ElMessage.success('已删除')
    if (items.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (e) {
    showError(e, '删除失败')
  }
}

function deleteDisabledReason(row: RunListItem): string {
  if (row.status === 'running') return '运行中不能删除'
  if (row.archived) return '已存档的运行不能删除，请先取消存档'
  return ''
}

onMounted(async () => {
  void load()
  try {
    tests.value = await testsApi.list()
  } catch {
    // 筛选项加载失败不影响列表
  }
})
onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(refreshTimer)
})
</script>

<template>
  <div class="page">
    <PageHeader>
      <el-button :icon="Refresh" @click="load()">刷新</el-button>
    </PageHeader>

    <div class="panel">
      <div class="filters">
        <el-select v-model="filters.testId" placeholder="全部测试" clearable filterable style="width: 200px" @change="onFilterChange">
          <el-option v-for="t in tests" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>
        <el-select v-model="filters.verdict" placeholder="全部判定" clearable style="width: 140px" @change="onFilterChange">
          <el-option v-for="v in VERDICT_OPTIONS" :key="v.value" :label="v.label" :value="v.value" />
        </el-select>
        <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 140px" @change="onFilterChange">
          <el-option label="运行中" value="running" />
          <el-option label="已结束" value="finished" />
        </el-select>
        <el-select v-model="filters.archived" placeholder="存档与否" clearable style="width: 140px" @change="onFilterChange">
          <el-option label="已存档" :value="true" />
          <el-option label="未存档" :value="false" />
        </el-select>
        <el-button link type="primary" @click="resetFilters">清空筛选</el-button>
      </div>

      <el-table v-loading="loading" :data="items" empty-text="没有符合条件的运行">
        <el-table-column label="开始时间" width="172">
          <template #default="{ row }">
            <router-link class="run-link num" :to="`/runs/${row.runId}`">{{ formatTime(row.startedAt) }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="测试 / 负载配置" min-width="190">
          <template #default="{ row }">
            <div class="cell-main" :title="row.testName">{{ row.testName }}</div>
            <div class="cell-sub" :title="row.profileName">{{ row.profileName }}</div>
          </template>
        </el-table-column>
        <el-table-column label="被测环境" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <EnvTypeTag :type="row.envType" class="env-tag" />{{ row.envName }}
          </template>
        </el-table-column>
        <el-table-column label="判定" width="104">
          <template #default="{ row }">
            <StatusTag v-if="row.status === 'running'" :status="row.status" />
            <VerdictTag v-else :verdict="row.verdict" />
          </template>
        </el-table-column>
        <el-table-column label="p95" width="84" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatMs(row.summary?.p95) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="错误率" width="76" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatPercent(row.summary?.errorRate) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="请求数" width="80" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatCount(row.summary?.reqs) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.archived" type="warning" effect="plain" size="small" class="archived-tag">已存档</el-tag>
            {{ row.note }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="196" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/runs/${row.runId}`)">查看</el-button>
            <el-button link type="primary" @click="toggleArchive(row as RunListItem)">
              {{ row.archived ? '取消存档' : '存档' }}
            </el-button>
            <el-tooltip
              :content="deleteDisabledReason(row as RunListItem)"
              :disabled="!deleteDisabledReason(row as RunListItem)"
              placement="top"
            >
              <span class="tooltip-anchor">
                <el-button
                  link
                  type="danger"
                  :disabled="!!deleteDisabledReason(row as RunListItem)"
                  @click="remove(row as RunListItem)"
                >
                  删除
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="load()"
          @size-change="onFilterChange"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.run-link {
  color: var(--el-color-primary);
  text-decoration: none;
}
.run-link:hover {
  text-decoration: underline;
}
.archived-tag,
.env-tag {
  margin-right: 6px;
}
.tooltip-anchor {
  display: inline-block;
  margin-left: 12px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
.cell-main,
.cell-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-sub {
  color: var(--ink-muted);
  font-size: 12px;
}
</style>
