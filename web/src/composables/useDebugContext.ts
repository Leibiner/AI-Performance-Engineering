import { computed, h, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { environmentsApi, type DebugResult, type Environment } from '../api'
import { showError } from '../utils/feedback'

const STORAGE_KEY = 'perf-console.debugEnvId'
/** 环境 id → { 变量名: 当前值 }。只存和初始值不同的；没有的就用初始值 */
const CURRENT_KEY = 'perf-console.debugCurrent'
/** 旧格式：环境 id → 完整的行（第一次用环境时从初始值复制而来） */
const LEGACY_KEY = 'perf-console.debugVars'

type Values = Record<string, string>

function readStoredEnvId(): number | undefined {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const n = raw === null ? NaN : Number(raw)
    return Number.isInteger(n) && n > 0 ? n : undefined
  } catch {
    return undefined
  }
}

function readJson(key: string): Record<string, unknown> {
  try {
    const raw = window.localStorage.getItem(key)
    const data = raw ? JSON.parse(raw) : {}
    return data && typeof data === 'object' ? data : {}
  } catch {
    return {}
  }
}

const envId = ref<number | undefined>(readStoredEnvId())
watch(envId, (value) => {
  try {
    if (value === undefined) window.localStorage.removeItem(STORAGE_KEY)
    else window.localStorage.setItem(STORAGE_KEY, String(value))
  } catch {
    // 隐私模式等情况下写不了，忽略
  }
})
const currentByEnv = ref<Record<string, Values>>(readJson(CURRENT_KEY) as Record<string, Values>)
watch(
  currentByEnv,
  (value) => {
    try {
      window.localStorage.setItem(CURRENT_KEY, JSON.stringify(value))
    } catch {
      // 写不了就只在本次会话里有效
    }
  },
  { deep: true },
)
const environments = ref<Environment[]>([])
const loaded = ref(false)
/** 环境 id → 等待保存初始值的定时器 */
const initialTimers: Record<number, number> = {}
const INITIAL_SAVE_DELAY_MS = 600

/**
 * 改某个环境的初始值（存在被测环境上，所有人共享，正式运行用的就是它）：本地立即生效，停顿一会儿后保存。
 * 保存成功不回填返回值：保存期间可能还在输入，回填会吞掉这些改动；失败时重新加载，回到库里的样子
 */
function setInitialVars(id: number, variables: Values): void {
  if (!environments.value.some((e) => e.id === id)) return
  environments.value = environments.value.map((e) => (e.id === id ? { ...e, variables } : e))
  window.clearTimeout(initialTimers[id])
  initialTimers[id] = window.setTimeout(() => {
    delete initialTimers[id]
    void saveInitial(id)
  }, INITIAL_SAVE_DELAY_MS)
}
async function saveInitial(id: number): Promise<void> {
  const env = environments.value.find((e) => e.id === id)
  if (!env) return
  try {
    await environmentsApi.update(id, env)
  } catch (e) {
    showError(e, '保存环境变量失败')
    try {
      environments.value = await environmentsApi.list()
    } catch {
      // 加载失败时保留本地的样子，下次打开页面会重新加载
    }
  }
}
// 关掉标签页时还有没保存的初始值：立即开始保存，并让浏览器先确认，给保存留出时间
window.addEventListener('beforeunload', (e) => {
  if (!Object.keys(initialTimers).length) return
  void flushEnvironmentEdits()
  e.preventDefault()
})

/** 把还没保存的初始值存下来。重新加载环境列表、切换页面之前调用，否则加载回来的旧值会盖掉它们 */
export async function flushEnvironmentEdits(): Promise<void> {
  for (const key of Object.keys(initialTimers)) {
    const id = Number(key)
    window.clearTimeout(initialTimers[id])
    delete initialTimers[id]
    await saveInitial(id)
  }
}
/** 本次会话里已经确认过"向生产环境发送"的被测环境 id */
const confirmedProd = ref<Set<number>>(new Set())

export function useDebugContext() {
  const environment = computed(() => environments.value.find((e) => e.id === envId.value) ?? null)
  const initialVars = computed<Values>(() => environment.value?.variables ?? {})

  function currentOf(id: number): Values {
    return currentByEnv.value[String(id)] ?? {}
  }
  function writeCurrent(id: number, values: Values): void {
    const next = { ...currentByEnv.value }
    if (Object.keys(values).length) next[String(id)] = values
    else delete next[String(id)]
    currentByEnv.value = next
  }
  /** 设置某个环境里一个变量的当前值 */
  function setCurrent(id: number, name: string, value: string): void {
    writeCurrent(id, { ...currentOf(id), [name]: value })
  }
  /** 清掉当前值，回到初始值（没有初始值就是没有这个变量） */
  function clearCurrent(id: number, name?: string): void {
    if (name === undefined) return writeCurrent(id, {})
    const next = { ...currentOf(id) }
    delete next[name]
    writeCurrent(id, next)
  }

  /** 当前调试环境里改过的当前值；调试请求只带这些，初始值由后端打底 */
  const overrides = computed<Values>(() => (environment.value ? currentOf(environment.value.id) : {}))
  /** 实际生效的变量：初始值 + 当前值 */
  const vars = computed<Values>(() => ({ ...initialVars.value, ...overrides.value }))
  const varCount = computed(() => Object.keys(vars.value).length)

  /** 一次调试结束后，把各步提取到的变量写进当前值。返回写入的变量名 */
  function applyExtracted(result: DebugResult): string[] {
    const env = environment.value
    if (!env) return []
    const updates: Values = {}
    for (const step of result.steps) {
      for (const e of step.extracted) {
        if (e.ok && e.value !== null) updates[e.var] = e.value
      }
    }
    const names = Object.keys(updates)
    if (names.length) writeCurrent(env.id, { ...currentOf(env.id), ...updates })
    return names
  }

  /** 旧格式里和初始值相同的是"复制来的"，丢掉；不同的才是当前值 */
  function migrateLegacy(): void {
    const legacy = readJson(LEGACY_KEY) as Record<string, { key: string; value: string }[]>
    if (!Object.keys(legacy).length) return
    for (const env of environments.value) {
      const rows = legacy[String(env.id)]
      if (!Array.isArray(rows)) continue
      const initial = env.variables ?? {}
      const kept: Values = { ...currentOf(env.id) }
      for (const r of rows) {
        const name = (r.key ?? '').trim()
        if (name && initial[name] !== r.value && !(name in kept)) kept[name] = r.value
      }
      writeCurrent(env.id, kept)
    }
    try {
      window.localStorage.removeItem(LEGACY_KEY)
    } catch {
      // 忽略
    }
  }

  async function loadEnvironments(): Promise<void> {
    await flushEnvironmentEdits()
    try {
      environments.value = await environmentsApi.list()
      loaded.value = true
      migrateLegacy()
      if (envId.value !== undefined && !environments.value.some((e) => e.id === envId.value)) envId.value = undefined
      if (envId.value === undefined && environments.value.length === 1) envId.value = environments.value[0].id
    } catch (e) {
      showError(e, '加载被测环境失败')
    }
  }

  const blocker = computed<string | null>(() => (environment.value ? null : '先选择被测环境'))

  /**
   * 被测环境是生产时，首次发送前弹一次确认；确认过的环境本次会话内不再问。
   * 返回 false 表示用户取消。非生产环境直接返回 true。
   */
  async function ensureProdConfirmed(): Promise<boolean> {
    const env = environment.value
    if (!env || env.type !== 'prod' || confirmedProd.value.has(env.id)) return true
    try {
      await ElMessageBox.confirm(
        h('div', { class: 'prod-confirm' }, [
          h('p', { class: 'prod-confirm-lead' }, '你正在向生产环境发送请求'),
          h('dl', [h('dt', '被测环境'), h('dd', env.name), h('dt', '地址'), h('dd', { class: 'mono' }, env.baseUrl)]),
          h('p', '调试会真实地发出 1 次请求。请确认已获得许可。确认后本次会话内对这个环境不再提示。'),
        ]),
        '向生产环境发送',
        {
          type: 'warning',
          confirmButtonText: '确认，发送',
          cancelButtonText: '取消',
          confirmButtonClass: 'el-button--danger',
          autofocus: false,
        },
      )
      confirmedProd.value.add(env.id)
      return true
    } catch {
      return false
    }
  }

  return {
    envId, vars, overrides, varCount, initialVars, setInitialVars, currentOf, setCurrent, clearCurrent, applyExtracted,
    environments, environment, loaded, loadEnvironments, blocker, ensureProdConfirmed,
  }
}
