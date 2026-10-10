<script setup lang="ts">
import { computed, ref } from 'vue'
import { dynamicArgProblem, dynamicVar, isDynamicRef, splitVars, varNames, type VarResolution, type VarState } from '../utils/vars'

// 输入框文字透明只留光标，底下一层逐字对齐地渲染文本，只给括号上色：
// {{ }} 按变量状态着色（有值蓝、待提取紫、未定义橙、不确定灰），普通 { } 用中性色；括号里的内容不加样式。
const model = defineModel<string>({ default: '' })
const props = withDefaults(
  defineProps<{
    vars?: Record<string, string>
    /** 变量名 → 提取它的接口名 */
    producers?: Record<string, string[]>
    /** 变量名 → 来源说明：有来源、但值要到发送时才知道（如数据集的列） */
    hints?: Record<string, string>
    /** 给出时由它决定每个引用的状态和说明，其余三项不再使用 */
    resolve?: (name: string) => VarResolution
    placeholder?: string
    multiline?: boolean
    rows?: number
    readonly?: boolean
    /** 去掉边框和圆角，嵌进别的容器 */
    seamless?: boolean
  }>(),
  {
    vars: () => ({}),
    producers: () => ({}),
    hints: () => ({}),
    resolve: undefined,
    placeholder: '',
    multiline: false,
    rows: 6,
    readonly: false,
    seamless: false,
  },
)

const segments = computed(() => splitVars(model.value ?? ''))
const has = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k)

function resolveName(name: string): VarResolution {
  if (props.resolve) return props.resolve(name)
  if (isDynamicRef(name)) {
    const d = dynamicVar(name)
    if (!d) return { state: 'is-unknown', title: `${name}：不是内置的动态变量` }
    const problem = dynamicArgProblem(name)
    return problem ? { state: 'is-unknown', title: `${name}：${problem}` } : { state: 'is-known', title: `${name}：${d.meaning}` }
  }
  if (has(props.vars, name)) return { state: 'is-known', title: `${name} = ${props.vars[name]}` }
  if (has(props.hints, name)) return { state: 'is-known', title: `${name}：${props.hints[name]}` }
  const by = props.producers[name]
  if (by?.length) return { state: 'is-extracted', title: `${name}：由「${by.join('、')}」提取，发送后才有值` }
  return { state: 'is-unknown', title: `${name}：未定义` }
}

const resolved = computed(() => {
  const out = new Map<string, VarResolution>()
  for (const seg of segments.value) if (seg.name && !out.has(seg.name)) out.set(seg.name, resolveName(seg.name))
  return out
})
function state(name: string): VarState {
  return resolved.value.get(name)?.state ?? 'is-unknown'
}
const title = computed(() => {
  const names = varNames(model.value ?? '')
  if (!names.length) return undefined
  return names.map((n) => resolved.value.get(n)?.title ?? n).join('\n')
})

const OPEN = '{{'
const CLOSE = '}}'

/** 普通文本按单个 { } 切开 */
function braceParts(text: string): string[] {
  return text.split(/([{}])/).filter((x) => x !== '')
}

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
        <template v-if="seg.name">
          <span class="var-brace" :class="state(seg.name)">{{ OPEN }}</span>{{ seg.text.slice(2, -2) }}<span class="var-brace" :class="state(seg.name)">{{ CLOSE }}</span>
        </template>
        <template v-else>
          <template v-for="(part, j) in braceParts(seg.text)" :key="j">
            <span v-if="part === '{' || part === '}'" class="brace">{{ part }}</span>
            <template v-else>{{ part }}</template>
          </template>
        </template>
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
.brace {
  color: #8a6d3b;
}
.var-brace.is-known {
  color: #1d6fd6;
}
.var-brace.is-extracted {
  color: #6a3fd1;
}
.var-brace.is-unknown {
  color: #d9480f;
}
.var-brace.is-unsure {
  color: #8a9099;
}
.var-brace {
  font-weight: inherit;
}
</style>
