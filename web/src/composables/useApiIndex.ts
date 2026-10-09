import { computed, ref } from 'vue'
import { apisApi, type ApiDef } from '../api'
import { varNames } from '../utils/vars'

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

  /** 变量名 → 提取它的接口名 */
  const producers = computed(() => {
    const out: Record<string, string[]> = {}
    for (const api of apis.value) for (const e of api.extracts ?? []) (out[e.var] ??= []).push(api.name)
    return out
  })

  /** 变量名 → 引用它的接口名 */
  const usages = computed(() => {
    const out: Record<string, string[]> = {}
    for (const api of apis.value) {
      const text = [api.path, ...Object.values(api.headers ?? {}), api.body ?? '', api.expectBodyContains ?? ''].join('\n')
      for (const name of varNames(text)) (out[name] ??= []).push(api.name)
    }
    return out
  })

  return { apis, refresh, producers, usages }
}
