<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  environmentsApi,
  executorsApi,
  profilesApi,
  type Environment,
  type Executor,
  type Profile,
  type TestDef,
} from '../api'
import { useStartRun } from '../composables/useStartRun'
import { showError } from '../utils/feedback'
import { formatLimit } from '../utils/env'
import { MODEL_LABELS, demandOf, describeConfig } from '../utils/profile'
import { DASH } from '../utils/format'
import EnvTypeTag from './EnvTypeTag.vue'

// 发起运行的对话框：选负载配置和被测环境，显示执行机和安全上限，确认后 POST /api/runs。
const visible = defineModel<boolean>({ required: true })
const props = defineProps<{ test: TestDef | null }>()

const { starting, start } = useStartRun()

const profiles = ref<Profile[]>([])
const environments = ref<Environment[]>([])
/** 将使用的执行机。目前只有本机一台，所以不提供选择 */
const executor = ref<Executor | null>(null)
const loading = ref(false)
const profileId = ref<number>()
const envId = ref<number>()
const note = ref('')
/** 预检被拒绝（422）时的逐条原因 */
const rejection = ref<{ message: string; details: string[] } | null>(null)

const profile = computed(() => profiles.value.find((p) => p.id === profileId.value) ?? null)
const environment = computed(() => environments.value.find((e) => e.id === envId.value) ?? null)

const over = (need: number | null | undefined, limit: number | null | undefined): boolean =>
  typeof need === 'number' && typeof limit === 'number' && need > limit

/** 负载配置的需求与被测环境安全上限的对照。上限为空表示不限制，不参与比较。只是提示，最终以后端预检为准。 */
const limitRows = computed(() => {
  const env = environment.value
  if (!env) return []
  const demand = profile.value ? demandOf(profile.value.model, profile.value.config) : null
  return [
    {
      name: '并发',
      need: demand ? `${demand.vus}` : DASH,
      limit: formatLimit(env.maxVus),
      over: over(demand?.vus, env.maxVus),
    },
    {
      name: '到达率',
      need: demand ? (demand.rate === null ? '不适用（closed 模型）' : `每秒 ${demand.rate} 次`) : DASH,
      limit: env.maxRate == null ? '不限制' : `每秒 ${env.maxRate} 次`,
      over: over(demand?.rate, env.maxRate),
    },
    {
      name: '总时长',
      need: demand ? `${demand.durationSec} 秒` : DASH,
      limit: formatLimit(env.maxDurationSec, '秒'),
      over: over(demand?.durationSec, env.maxDurationSec),
    },
  ]
})
const overLimit = computed(() => limitRows.value.some((row) => row.over))

async function loadOptions(): Promise<void> {
  loading.value = true
  try {
    const [p, e] = await Promise.all([profilesApi.list(), environmentsApi.list()])
    profiles.value = p
    environments.value = e
    // 只有一个可选项时直接选上
    if (p.length === 1) profileId.value = p[0].id
    if (e.length === 1) envId.value = e[0].id
  } catch (err) {
    showError(err, '加载负载配置和被测环境失败')
  } finally {
    loading.value = false
  }
}

async function loadExecutor(): Promise<void> {
  // 取不到执行机不影响发起：请求里不带 executorId，后端默认用本机执行机
  try {
    const list = await executorsApi.list()
    executor.value = list[0] ?? null
  } catch {
    executor.value = null
  }
}

watch(visible, (open) => {
  if (!open) return
  profileId.value = undefined
  envId.value = undefined
  note.value = ''
  rejection.value = null
  void loadOptions()
  void loadExecutor()
})

// 改了选择后，上一次的拒绝原因不再适用
watch([profileId, envId], () => {
  rejection.value = null
})

async function confirm(): Promise<void> {
  const env = environment.value
  if (!props.test || profileId.value === undefined || !env) return
  rejection.value = null
  const ok = await start(
    {
      testId: props.test.id,
      profileId: profileId.value,
      envId: env.id,
      ...(executor.value ? { executorId: executor.value.id } : {}),
      note: note.value,
    },
    {
      // 被测环境是生产时，start 会先弹二次确认
      env,
      onPreflightRejected: (error) => {
        rejection.value = { message: error.message, details: error.details }
      },
    },
  )
  if (ok) visible.value = false
}
</script>

<template>
  <el-dialog v-model="visible" title="发起运行" width="700px" top="8vh" :close-on-click-modal="false">
    <el-form v-loading="loading" label-width="90px">
      <el-form-item label="测试">
        <strong>{{ test?.name }}</strong>
      </el-form-item>
      <el-form-item label="负载配置" required>
        <el-select v-model="profileId" placeholder="选择负载配置" style="width: 100%" no-data-text="还没有负载配置">
          <el-option v-for="p in profiles" :key="p.id" :label="`${p.name}（${p.model}）`" :value="p.id" />
        </el-select>
        <div v-if="profile" class="form-hint">
          {{ MODEL_LABELS[profile.model] }}：{{ describeConfig(profile.model, profile.config) }}
        </div>
      </el-form-item>
      <el-form-item label="被测环境" required>
        <el-select v-model="envId" placeholder="选择被测环境" style="width: 100%" no-data-text="还没有被测环境">
          <el-option v-for="e in environments" :key="e.id" :label="e.name" :value="e.id">
            <span class="env-option">
              <span>{{ e.name }}</span>
              <EnvTypeTag :type="e.type" />
            </span>
          </el-option>
        </el-select>
        <div v-if="environment" class="form-hint env-hint">
          <EnvTypeTag :type="environment.type" />
          <span>
            请求会发往 <span class="mono">{{ environment.baseUrl }}</span>
          </span>
        </div>
        <div v-if="environment?.type === 'prod'" class="form-hint limit-warn">
          这是生产环境。点“开始运行”后会再确认一次。
        </div>
      </el-form-item>

      <el-form-item label="执行机">
        <template v-if="executor">
          <span>{{ executor.name }}</span>
          <span class="muted executor-host">
            主机 <span class="mono">{{ executor.host ?? DASH }}</span>
            <template v-if="executor.ip"> · <span class="mono">{{ executor.ip }}</span></template>
          </span>
        </template>
        <span v-else class="muted">本机执行机（默认）</span>
        <div class="form-hint">k6 在这台机器上运行，并从它向被测环境发出请求。</div>
      </el-form-item>

      <el-form-item v-if="environment" label="安全上限">
        <table class="limit-table">
          <thead>
            <tr>
              <th />
              <th>负载配置需要</th>
              <th>被测环境的上限</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in limitRows" :key="row.name" :class="{ 'is-over': row.over }">
              <td>{{ row.name }}</td>
              <td>{{ row.need }}</td>
              <td :class="{ muted: row.limit === '不限制' }">{{ row.limit }}</td>
              <td>{{ row.over ? '超过上限' : '' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="overLimit" class="form-hint limit-warn">
          这个负载配置超过了被测环境的安全上限，发起后会被预检拒绝。请换一个负载更小的负载配置，或者换一个允许这个流量的被测环境。安全上限是对目标系统的保护，不要为了让运行通过而调高它。
        </div>
      </el-form-item>

      <el-form-item label="备注">
        <el-input v-model="note" placeholder="可选，例如这次运行的目的" maxlength="200" />
      </el-form-item>
    </el-form>

    <el-alert v-if="rejection" type="error" :closable="false" show-icon :title="rejection.message || '预检未通过，没有发起运行'">
      <ul v-if="rejection.details.length" class="reject-list">
        <li v-for="(item, index) in rejection.details" :key="index">{{ item }}</li>
      </ul>
    </el-alert>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button
        type="primary"
        :loading="starting"
        :disabled="profileId === undefined || envId === undefined"
        @click="confirm"
      >
        开始运行
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.env-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.env-hint {
  display: flex;
  align-items: center;
  gap: 8px;
}
.executor-host {
  margin-left: 10px;
  font-size: 13px;
}
.limit-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.5;
}
.limit-table th,
.limit-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--hairline);
  text-align: left;
}
.limit-table th {
  color: var(--ink-muted);
  font-weight: 400;
}
.limit-table tr.is-over td {
  color: var(--el-color-danger);
  font-weight: 600;
}
.limit-warn {
  color: var(--el-color-danger);
}
.reject-list {
  margin: 4px 0 0;
  padding-left: 18px;
  line-height: 1.8;
}
</style>
