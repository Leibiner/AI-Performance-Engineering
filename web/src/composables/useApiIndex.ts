import { computed, ref } from 'vue'
import { apisApi, type ApiDef } from '../api'
import { apiRefs } from '../utils/var-sources'
import { isDynamicRef } from '../utils/vars'

// 已保存接口的变量索引：谁提取了哪个变量、谁引用了哪个变量。接口页、流程页、被测环境页共用一份。
const apis = ref<ApiDef[]>([])

export function useApiIndex() {
  async function refresh(): Promise<void> {
    try {
      apis.value = await apisApi.list()
    } catch {
      // 索引只用于展示，取不到就留空
    }
  }

  /** 变量名 → 提取它的接口 */
  const producerApis = computed(() => {
    const out: Record<string, ApiDef[]> = {}
    for (const api of apis.value) {
      for (const name of new Set((api.extracts ?? []).map((e) => e.var))) (out[name] ??= []).push(api)
    }
    return out
  })

  /** 变量名 → 提取它的接口名 */
  const producers = computed(() => {
    const out: Record<string, string[]> = {}
    for (const [name, list] of Object.entries(producerApis.value)) out[name] = list.map((a) => a.name)
    return out
  })

  /** 变量名 → 引用它的接口名 */
  const usages = computed(() => {
    const out: Record<string, string[]> = {}
    for (const api of apis.value) {
      for (const name of apiRefs(api)) if (!isDynamicRef(name)) (out[name] ??= []).push(api.name)
    }
    return out
  })

  return { apis, refresh, producers, producerApis, usages }
}
