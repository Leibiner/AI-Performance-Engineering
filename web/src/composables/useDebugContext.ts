import { computed, ref, watch } from 'vue'
import { environmentsApi, type Environment } from '../api'
import { showError } from '../utils/feedback'
import { fromRows, type KvRow } from '../utils/kv'

// 调试上下文：选中的被测环境、初始变量、生产环境的确认。放在模块级，切换页面后还在，
// 像 Postman 右上角的环境选择一样是"当前工作环境"，不是某个表单的字段。
const envId = ref<number | undefined>()
const varRows = ref<KvRow[]>([])
const prodConfirmed = ref(false)
const environments = ref<Environment[]>([])
const loaded = ref(false)

// 换了环境，之前对生产环境的确认不再算数
watch(envId, () => {
  prodConfirmed.value = false
})

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
  const blocker = computed<string | null>(() => {
    if (!environment.value) return '先选择被测环境'
    if (environment.value.type === 'prod' && !prodConfirmed.value) return '生产环境需要先勾选确认'
    return null
  })

  return { envId, varRows, vars, varCount, prodConfirmed, environments, environment, loaded, loadEnvironments, blocker }
}
