import { computed, h, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { environmentsApi, type Environment } from '../api'
import { showError } from '../utils/feedback'
import { fromRows, type KvRow } from '../utils/kv'

// 调试上下文：当前调试环境、初始变量、已经确认过的生产环境。放在模块级，切换页面后还在，
// 像 Postman 右上角的环境选择一样是"当前工作环境"，不是某个接口的字段：
// 页头右上角、接口页请求栏里的地址前缀、流程试跑对话框里的选择器，改的都是同一个值。
// 环境 id 存 localStorage，刷新后还在；变量和生产确认只在本次会话里。
const STORAGE_KEY = 'perf-console.debugEnvId'

function readStoredEnvId(): number | undefined {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const n = raw === null ? NaN : Number(raw)
    return Number.isInteger(n) && n > 0 ? n : undefined
  } catch {
    return undefined
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
const varRows = ref<KvRow[]>([])
const environments = ref<Environment[]>([])
const loaded = ref(false)
/** 本次会话里已经确认过"向生产环境发送"的被测环境 id */
const confirmedProd = ref<Set<number>>(new Set())

export function useDebugContext() {
  const environment = computed(() => environments.value.find((e) => e.id === envId.value) ?? null)
  const vars = computed(() => fromRows(varRows.value))
  const varCount = computed(() => varRows.value.filter((r) => r.key.trim() !== '').length)

  async function loadEnvironments(): Promise<void> {
    try {
      environments.value = await environmentsApi.list()
      loaded.value = true
      if (envId.value !== undefined && !environments.value.some((e) => e.id === envId.value)) envId.value = undefined
      if (envId.value === undefined && environments.value.length === 1) envId.value = environments.value[0].id
    } catch (e) {
      showError(e, '加载被测环境失败')
    }
  }

  /** 现在能不能发送；不能时返回原因 */
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

  return { envId, varRows, vars, varCount, environments, environment, loaded, loadEnvironments, blocker, ensureProdConfirmed }
}
