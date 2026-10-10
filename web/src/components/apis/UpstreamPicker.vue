<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import type { ApiDef } from '../../api'
import { METHOD_COLOR } from '../../utils/method'

export interface UpstreamCandidate {
  api: ApiDef
  /** 它提取、本接口引用的变量 */
  vars: string[]
}

/** 按选择顺序执行 */
const selected = defineModel<number[]>({ required: true })
const props = defineProps<{
  candidates: UpstreamCandidate[]
  /** 引用了、当前值和初始值都没有、但有接口能提取的变量 */
  pending: string[]
}>()

const MAX = 5

function toggle(id: number): void {
  if (selected.value.includes(id)) selected.value = selected.value.filter((x) => x !== id)
  else if (selected.value.length < MAX) selected.value = [...selected.value, id]
}
const order = (id: number) => selected.value.indexOf(id) + 1
const full = computed(() => selected.value.length >= MAX)
const buttonTitle = computed(() => {
  if (selected.value.length) {
    const names = selected.value.map((id) => props.candidates.find((c) => c.api.id === id)?.api.name ?? `#${id}`)
    return `发送时先运行：${names.join(' → ')}`
  }
  return props.pending.length ? `还没有值：${props.pending.join('、')}` : '先运行上游接口'
})
</script>

<template>
  <el-popover placement="bottom-end" :width="460" trigger="click">
    <template #reference>
      <span class="upstream-ref">
        <el-badge
          :value="selected.length"
          :is-dot="!selected.length && pending.length > 0"
          :hidden="!selected.length && !pending.length"
          :type="selected.length ? 'primary' : 'warning'"
        >
          <el-button
            type="primary"
            class="upstream-caret"
            aria-label="上游接口"
            :title="buttonTitle"
            :disabled="!candidates.length && !selected.length"
          >
            <el-icon><ArrowDown /></el-icon>
          </el-button>
        </el-badge>
      </span>
    </template>
    <div class="upstream">
      <div class="upstream-head">先运行</div>
      <div
        v-for="c in candidates"
        :key="c.api.id"
        class="upstream-item"
        :class="{ 'is-on': order(c.api.id) > 0, 'is-disabled': full && order(c.api.id) === 0 }"
        @click="toggle(c.api.id)"
      >
        <span class="upstream-order">{{ order(c.api.id) || '' }}</span>
        <span class="upstream-method" :style="{ color: METHOD_COLOR[c.api.method] }">{{ c.api.method }}</span>
        <span class="upstream-name" :title="`${c.api.method} ${c.api.path}`">{{ c.api.name }}</span>
        <span class="upstream-vars mono">
          <span v-for="v in c.vars" :key="v" :class="{ 'is-pending': pending.includes(v) }">{{ v }}</span>
        </span>
      </div>
      <div v-if="!candidates.length" class="upstream-empty">没有接口提取本接口用到的变量</div>
      <div v-if="selected.length" class="upstream-foot">
        <span class="muted">{{ selected.length }} / {{ MAX }}</span>
        <el-button link type="primary" @click="selected = []">清空</el-button>
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.upstream-ref {
  display: inline-flex;
}
.upstream-caret {
  padding: 8px 9px;
  border-left-color: rgba(255, 255, 255, 0.55);
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}
.upstream-head {
  margin: 0 0 4px 8px;
  color: var(--ink-muted);
  font-size: 12px;
}
.upstream-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}
.upstream-item:hover {
  background: #f4f5f7;
}
.upstream-item.is-on {
  background: rgba(64, 158, 255, 0.1);
}
.upstream-item.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.upstream-order {
  display: inline-block;
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border: 1px solid var(--el-border-color);
  border-radius: 50%;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
}
.is-on .upstream-order {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}
.upstream-method {
  flex-shrink: 0;
  width: 46px;
  font-size: 11px;
  font-weight: 700;
}
.upstream-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.upstream-vars {
  display: flex;
  flex-shrink: 0;
  gap: 6px;
  max-width: 45%;
  overflow: hidden;
  color: #6a3fd1;
}
.upstream-vars .is-pending {
  color: #d9480f;
  font-weight: 600;
}
.upstream-empty {
  padding: 10px 4px;
  color: var(--ink-muted);
  font-size: 13px;
}
.upstream-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  padding: 6px 8px 0;
  border-top: 1px solid var(--hairline);
  font-size: 12px;
}
</style>
