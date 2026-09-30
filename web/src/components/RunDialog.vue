<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { environmentsApi, profilesApi, type Environment, type Profile, type TestDef } from '../api'
import { useStartRun } from '../composables/useStartRun'
import { showError } from '../utils/feedback'
import { MODEL_LABELS, demandOf, describeConfig } from '../utils/profile'
import { DASH } from '../utils/format'

// 发起运行的对话框：选负载配置和环境，显示环境的流量上限，确认后 POST /api/runs。
const visible = defineModel<boolean>({ required: true })
const props = defineProps<{ test: TestDef | null }>()

const { starting, start } = useStartRun()

const profiles = ref<Profile[]>([])
const environments = ref<Environment[]>([])
const loading = ref(false)
const profileId = ref<number>()
const envId = ref<number>()
const note = ref('')
/** 预检被拒绝（422）时的逐条原因 */
const rejection = ref<{ message: string; details: string[] } | null>(null)

const profile = computed(() => profiles.value.find((p) => p.id === profileId.value) ?? null)
const environment = computed(() => environments.value.find((e) => e.id === envId.value) ?? null)

/** 负载配置的需求与环境上限的对照。只是提示，最终以后端预检为准。 */
const limitRows = computed(() => {
  const env = environment.value
  if (!env) return []
  const demand = profile.value ? demandOf(profile.value.model, profile.value.config) : null
  return [
    { name: '并发', need: demand ? `${demand.vus}` : DASH, limit: `${env.maxVus}`, over: !!demand && demand.vus > env.maxVus },
    {
      name: '到达率',
      need: demand ? (demand.rate === null ? '不适用（closed 模型）' : `每秒 ${demand.rate} 次`) : DASH,
      limit: `每秒 ${env.maxRate} 次`,
      over: !!demand && demand.rate !== null && demand.rate > env.maxRate,
    },
    {
      name: '总时长',
      need: demand ? `${demand.durationSec} 秒` : DASH,
      limit: `${env.maxDurationSec} 秒`,
      over: !!demand && demand.durationSec > env.maxDurationSec,
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
    showError(err, '加载负载配置和环境失败')
  } finally {
    loading.value = false
  }
}

watch(visible, (open) => {
  if (!open) return
  profileId.value = undefined
  envId.value = undefined
  note.value = ''
  rejection.value = null
  void loadOptions()
})

// 改了选择后，上一次的拒绝原因不再适用
watch([profileId, envId], () => {
  rejection.value = null
})

async function confirm(): Promise<void> {
  if (!props.test || profileId.value === undefined || envId.value === undefined) return
  rejection.value = null
  const ok = await start(
    { testId: props.test.id, profileId: profileId.value, envId: envId.value, note: note.value },
    {
      onPreflightRejected: (error) => {
        rejection.value = { message: error.message, details: error.details }
      },
    },
  )
  if (ok) visible.value = false
}
</script>

<template>
  <el-dialog v-model="visible" title="发起运行" width="680px" :close-on-click-modal="false">
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
      <el-form-item label="环境" required>
        <el-select v-model="envId" placeholder="选择环境" style="width: 100%" no-data-text="还没有环境">
          <el-option v-for="e in environments" :key="e.id" :label="e.name" :value="e.id" />
        </el-select>
        <div v-if="environment" class="form-hint">
          请求会发往 <span class="mono">{{ environment.baseUrl }}</span>
        </div>
      </el-form-item>

      <el-form-item v-if="environment" label="流量上限">
        <table class="limit-table">
          <thead>
            <tr>
              <th />
              <th>负载配置需要</th>
              <th>环境上限</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in limitRows" :key="row.name" :class="{ 'is-over': row.over }">
              <td>{{ row.name }}</td>
              <td>{{ row.need }}</td>
              <td>{{ row.limit }}</td>
              <td>{{ row.over ? '超过上限' : '' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="overLimit" class="form-hint limit-warn">
          这个负载配置超过了环境的流量上限，发起后会被预检拒绝。请换一个负载配置，或者调整环境的上限。
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
