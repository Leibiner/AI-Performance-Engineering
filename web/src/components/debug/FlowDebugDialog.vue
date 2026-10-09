<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { VideoPlay } from '@element-plus/icons-vue'
import type { Flow } from '../../api'
import { useDebug } from '../../composables/useDebug'
import { useDebugContext } from '../../composables/useDebugContext'
import { STEP_STATUS } from '../../utils/debug'
import { formatMs } from '../../utils/format'
import DebugErrorView from './DebugErrorView.vue'
import DebugStepPanel from './DebugStepPanel.vue'
import VariablesTable from './VariablesTable.vue'
import EnvPicker from './EnvPicker.vue'

const visible = defineModel<boolean>({ required: true })
const props = defineProps<{ flow: Flow | null }>()

const ctx = useDebugContext()
const { running, result, error, run, reset } = useDebug()
const opened = ref<string[]>([])
const updatedVars = ref<string[]>([])

watch(visible, (open) => {
  if (open) {
    reset()
    opened.value = []
  }
})

const passedCount = computed(() => result.value?.steps.filter((s) => s.status === 'passed').length ?? 0)

async function start(): Promise<void> {
  const env = ctx.environment.value
  if (!props.flow || !env || ctx.blocker.value) return
  if (!(await ctx.ensureProdConfirmed())) return
  const r = await run({
    envId: env.id,
    ...(env.type === 'prod' ? { confirmProd: true } : {}),
    vars: ctx.overrides.value,
    flowId: props.flow.id,
  })
  updatedVars.value = r ? ctx.applyExtracted(r) : []
  if (r) {
    // 默认展开第一个没通过的步骤；全通过时展开第一步
    const first = r.steps.find((s) => s.status !== 'passed') ?? r.steps[0]
    opened.value = first ? [first.key] : []
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="`试跑业务流程：${flow?.name ?? ''}`" width="1000px" top="5vh" :close-on-click-modal="false">
    <div class="flow-debug-bar">
      <span class="muted">发往</span>
      <EnvPicker />
      <el-popover v-if="ctx.environment.value" placement="bottom-start" :width="860" trigger="click">
        <template #reference>
          <el-button text bg>
            变量
            <span v-if="ctx.varCount.value" class="flow-debug-count">{{ ctx.varCount.value }}</span>
          </el-button>
        </template>
        <VariablesTable :env-id="ctx.environment.value.id" :initial="ctx.initialVars.value" />
      </el-popover>
      <span class="flow-debug-spacer" />
      <el-tooltip :content="ctx.blocker.value ?? ''" :disabled="!ctx.blocker.value" placement="top">
        <span>
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!!ctx.blocker.value" @click="start">
            {{ running ? '正在执行…' : '试跑一次' }}
          </el-button>
        </span>
      </el-tooltip>
    </div>

    <DebugErrorView v-if="error" :error="error" />

    <template v-else-if="result">
      <div class="flow-debug-summary" :class="result.ok ? 'is-ok' : 'is-bad'">
        <strong>{{ result.ok ? '全部步骤通过' : `${passedCount} / ${result.steps.length} 步通过` }}</strong>
        <span v-if="updatedVars.length" class="muted">已更新变量 <span class="mono">{{ updatedVars.join('、') }}</span></span>
      </div>
      <el-collapse v-model="opened" class="flow-steps">
        <el-collapse-item v-for="(step, index) in result.steps" :key="step.key" :name="step.key">
          <template #title>
            <span class="flow-step-title">
              <span class="row-index">{{ index + 1 }}</span>
              <el-tag :type="STEP_STATUS[step.status].tag" size="small" effect="dark" class="flow-step-status">
                {{ STEP_STATUS[step.status].label }}
              </el-tag>
              <span class="flow-step-name">{{ step.name }}</span>
              <span v-if="step.request" class="mono muted flow-step-url">{{ step.request.method }} {{ step.request.url }}</span>
              <span v-if="step.response" class="num muted flow-step-ms">{{ formatMs(step.timings?.durationMs) }}</span>
            </span>
          </template>
          <DebugStepPanel :step="step" />
        </el-collapse-item>
      </el-collapse>
    </template>

    <div v-else-if="!running" class="flow-debug-empty">点击试跑查看各步骤结果</div>
  </el-dialog>
</template>

<style scoped>
.flow-debug-hint {
  margin: -6px 0 12px;
}
.flow-debug-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  background: #fafbfc;
  margin-bottom: 14px;
}
.flow-debug-spacer {
  flex: 1;
}
.flow-debug-count {
  display: inline-block;
  min-width: 18px;
  margin-left: 6px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}
.flow-debug-summary {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 10px;
  padding: 8px 12px;
  border-radius: 6px;
}
.flow-debug-summary.is-ok {
  background: #e6f4ea;
  color: #1f8a3b;
}
.flow-debug-summary.is-bad {
  background: #fbe9e9;
  color: #d03b3b;
}
.flow-step-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
  padding-right: 12px;
}
.flow-step-status {
  flex-shrink: 0;
}
.flow-step-name {
  font-weight: 600;
  flex-shrink: 0;
}
.flow-step-url {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.flow-step-ms {
  margin-left: auto;
  flex-shrink: 0;
}
.flow-steps :deep(.el-collapse-item__content) {
  padding: 4px 8px 16px;
}
.flow-debug-empty {
  padding: 28px 0;
  color: var(--ink-muted);
  text-align: center;
}
</style>
