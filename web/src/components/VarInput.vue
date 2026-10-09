<script setup lang="ts">
import { computed, ref } from 'vue'
import { splitVars, varNames } from '../utils/vars'

// 带变量高亮的输入框：输入框文字透明只留光标，底下一层逐字对齐地渲染文本，{{变量}} 上色。
// 有当前值的蓝色；没值但有接口会提取它的紫色；两者都不是的橙色加波浪线（多半拼错或漏定义）。
const model = defineModel<string>({ default: '' })
const props = withDefaults(
  defineProps<{
    vars?: Record<string, string>
    /** 变量名 → 提取它的接口名 */
    producers?: Record<string, string[]>
    placeholder?: string
    multiline?: boolean
    rows?: number
    readonly?: boolean
    /** 去掉边框和圆角，嵌进别的容器 */
    seamless?: boolean
  }>(),
  { vars: () => ({}), producers: () => ({}), placeholder: '', multiline: false, rows: 6, readonly: false, seamless: false },
)

const segments = computed(() => splitVars(model.value ?? ''))
const has = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k)
function state(name: string): 'is-known' | 'is-extracted' | 'is-unknown' {
  if (has(props.vars, name)) return 'is-known'
  return props.producers[name]?.length ? 'is-extracted' : 'is-unknown'
}
const title = computed(() => {
  const names = varNames(model.value ?? '')
  if (!names.length) return undefined
  return names
    .map((n) => {
      if (has(props.vars, n)) return `${n} = ${props.vars[n]}`
      const by = props.producers[n]
      return by?.length ? `${n}：由「${by.join('、')}」提取，发送后才有值` : `${n}：未定义`
    })
    .join('\n')
})

const layer = ref<HTMLElement>()
function syncScroll(e: Event): void {
  const el = e.target as HTMLElement
  if (layer.value) {
    layer.value.scrollTop = el.scrollTop
    layer.value.scrollLeft = el.scrollLeft
  }
}
</script>

<template>
  <div class="var-field" :class="{ 'is-multiline': multiline, 'is-seamless': seamless, 'is-readonly': readonly }" :title="title">
    <div ref="layer" class="var-layer" aria-hidden="true">
      <template v-for="(seg, i) in segments" :key="i">
        <span v-if="seg.name" class="var-ref" :class="state(seg.name)">{{ seg.text }}</span>
        <template v-else>{{ seg.text }}</template>
      </template>
      <!-- 末尾换行时撑出最后一行的高度 -->
      <template v-if="multiline">&#8203;</template>
    </div>
    <textarea
      v-if="multiline"
      v-model="model"
      class="var-control"
      :rows="rows"
      :placeholder="placeholder"
      :readonly="readonly"
      spellcheck="false"
      @scroll="syncScroll"
    />
    <input
      v-else
      v-model="model"
      class="var-control"
      :placeholder="placeholder"
      :readonly="readonly"
      spellcheck="false"
      @scroll="syncScroll"
      @input="syncScroll"
      @keyup="syncScroll"
      @click="syncScroll"
    />
  </div>
</template>

<style scoped>
.var-field {
  position: relative;
  width: 100%;
  border-radius: var(--el-border-radius-base);
  background: var(--el-fill-color-blank);
  box-shadow: 0 0 0 1px var(--el-border-color) inset;
  transition: box-shadow 0.15s;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 20px;
}
.var-field:hover {
  box-shadow: 0 0 0 1px var(--el-border-color-hover) inset;
}
.var-field:focus-within {
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}
.var-field.is-seamless,
.var-field.is-seamless:hover,
.var-field.is-seamless:focus-within {
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}
.var-field.is-readonly {
  background: #fafbfc;
}
.var-layer,
.var-control {
  box-sizing: border-box;
  width: 100%;
  margin: 0;
  padding: 5px 11px;
  border: 0;
  font: inherit;
  letter-spacing: normal;
  white-space: pre;
  overflow: hidden;
}
.var-layer {
  position: absolute;
  inset: 0;
  color: var(--el-text-color-regular);
  pointer-events: none;
}
.var-control {
  position: relative;
  display: block;
  height: 32px;
  background: transparent;
  color: transparent;
  caret-color: var(--el-text-color-primary);
  outline: none;
}
.var-control::placeholder {
  color: var(--el-text-color-placeholder);
}
.var-control::selection {
  background: rgba(64, 158, 255, 0.25);
}
.is-multiline .var-layer,
.is-multiline .var-control {
  white-space: pre-wrap;
  word-break: break-all;
  overflow-wrap: anywhere;
  padding: 6px 11px;
}
.is-multiline .var-control {
  height: auto;
  min-height: 60px;
  resize: vertical;
  overflow: auto;
}
.var-ref {
  border-radius: 3px;
}
.var-ref.is-known {
  background: rgba(64, 158, 255, 0.14);
  color: #1d6fd6;
}
.var-ref.is-extracted {
  background: rgba(124, 77, 255, 0.12);
  color: #6a3fd1;
}
.var-ref.is-unknown {
  background: rgba(230, 162, 60, 0.16);
  color: #c45a00;
  text-decoration: underline wavy rgba(230, 120, 0, 0.7);
  text-underline-offset: 3px;
}
</style>
