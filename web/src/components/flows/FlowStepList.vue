<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown, ArrowUp, Bottom, Delete, Plus, Top } from '@element-plus/icons-vue'
import type { ApiDef, StepPhase } from '../../api'
import type { StepVars } from '../../utils/var-sources'

export interface StepRow {
  /** 只用作 v-for 的 key：步骤在列表间移动时保持输入框状态 */
  key: number
  apiId: number | undefined
  thinkTimeMs: number | null | undefined
}
export interface ApiGroup {
  label: string
  apis: ApiDef[]
}

const steps = defineModel<StepRow[]>({ required: true })
const props = defineProps<{
  phase: StepPhase
  apis: ApiDef[]
  /** 有文件夹时按文件夹分组 */
  groups: ApiGroup[] | null
  checks: (StepVars | null)[]
  /** 引用的接口已被删除的 id（来自后端返回的流程：apiName 为 null） */
  missing?: Set<number>
}>()
const isMissing = (step: StepRow): boolean =>
  step.apiId !== undefined && !!props.missing?.has(step.apiId) && !props.apis.some((a) => a.id === step.apiId)
const emit = defineEmits<{ add: []; move: [index: number] }>()

function moveWithin(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= steps.value.length) return
  const [step] = steps.value.splice(index, 1)
  steps.value.splice(target, 0, step)
}
const apiLabel = (api: ApiDef) => `${api.name}（${api.method} ${api.path}）`
const entries = computed(() => steps.value.map((step, index) => ({ step, index, vars: props.checks[index] ?? null })))
</script>

<template>
  <div class="row-list step-list">
    <div v-if="steps.length" class="row-item row-head">
      <span class="row-index" />
      <span class="grow">接口</span>
      <span class="step-wait">执行后等待（毫秒）</span>
      <span class="step-ops" />
    </div>
    <div v-for="{ step, index, vars } in entries" :key="step.key" class="step">
      <div class="row-item">
        <span class="row-index">{{ index + 1 }}</span>
        <el-select
          v-model="step.apiId"
          :class="['grow', { 'is-missing': isMissing(step) }]"
          filterable
          placeholder="选择接口"
          no-data-text="还没有接口，请先到“接口”页面新建"
        >
          <template v-if="groups">
            <el-option-group v-for="group in groups" :key="group.label" :label="group.label">
              <el-option v-for="api in group.apis" :key="api.id" :label="apiLabel(api)" :value="api.id" />
            </el-option-group>
          </template>
          <template v-else>
            <el-option v-for="api in apis" :key="api.id" :label="apiLabel(api)" :value="api.id" />
          </template>
          <el-option v-if="isMissing(step)" :value="step.apiId!" :label="`接口已删除（#${step.apiId}）`" />
        </el-select>
        <el-input-number
          v-model="step.thinkTimeMs"
          :min="0"
          :step="100"
          :precision="0"
          controls-position="right"
          class="step-wait"
        />
        <span class="step-ops">
          <el-button :icon="ArrowUp" circle text title="上移" :disabled="index === 0" @click="moveWithin(index, -1)" />
          <el-button
            :icon="ArrowDown"
            circle
            text
            title="下移"
            :disabled="index === steps.length - 1"
            @click="moveWithin(index, 1)"
          />
          <el-button
            :icon="phase === 'init' ? Bottom : Top"
            circle
            text
            :title="phase === 'init' ? '移到每次迭代' : '移到初始化'"
            @click="emit('move', index)"
          />
          <el-button :icon="Delete" circle text title="删除这一步" @click="steps.splice(index, 1)" />
        </span>
      </div>
      <div v-if="vars && (vars.uses.length || vars.produces.length)" class="step-vars">
        <span v-if="vars.uses.length" class="step-vars-group">
          <span class="step-vars-label">用到</span>
          <el-tooltip
            v-for="u in vars.uses"
            :key="u.name"
            :content="u.title"
            placement="top"
            :show-after="120"
          >
            <span class="var-chip" :class="`is-${u.state}`">{{ u.name }}</span>
          </el-tooltip>
        </span>
        <span v-if="vars.produces.length" class="step-vars-group">
          <span class="step-vars-label">产出</span>
          <span v-for="p in vars.produces" :key="p" class="var-chip is-produce">{{ p }}</span>
        </span>
      </div>
    </div>
    <el-button :icon="Plus" size="small" @click="emit('add')">添加步骤</el-button>
  </div>
</template>

<style scoped>
.is-missing :deep(.el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.is-missing :deep(.el-select__selected-item) {
  color: var(--el-color-danger);
}
.step-wait {
  flex-shrink: 0;
  width: 150px;
}
.step-ops {
  display: inline-flex;
  flex-shrink: 0;
  width: 140px;
}
.step-ops .el-button + .el-button {
  margin-left: 0;
}
.step + .step {
  margin-top: 2px;
}
.step-vars {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin: -4px 0 8px 30px;
}
.step-vars-group {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.step-vars-label {
  color: var(--ink-muted);
  font-size: 12px;
}
.var-chip {
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 18px;
  cursor: default;
}
.var-chip.is-ok {
  border-color: rgba(29, 111, 214, 0.3);
  background: rgba(29, 111, 214, 0.06);
  color: #1d6fd6;
}
.var-chip.is-missing {
  border-color: rgba(208, 59, 59, 0.45);
  background: #fbe9e9;
  color: #d03b3b;
  font-weight: 600;
}
.var-chip.is-unsure {
  border-color: var(--hairline);
  background: #f4f5f7;
  color: #6b7280;
}
.var-chip.is-produce {
  border-color: rgba(124, 77, 255, 0.35);
  background: rgba(124, 77, 255, 0.06);
  color: #6a3fd1;
}
</style>
