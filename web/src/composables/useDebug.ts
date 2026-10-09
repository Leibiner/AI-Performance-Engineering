import { ref } from 'vue'
import { ApiError, debugApi, type DebugInput, type DebugResult } from '../api'
import { showError } from '../utils/feedback'

/** 发一次调试请求。后端返回的错误（预检、冲突、k6 失败）留在 error 里，由响应面板就地显示，不弹框。 */
export function useDebug() {
  const running = ref(false)
  const result = ref<DebugResult | null>(null)
  const error = ref<ApiError | null>(null)

  async function run(input: DebugInput): Promise<DebugResult | null> {
    running.value = true
    error.value = null
    try {
      result.value = await debugApi.run(input)
      return result.value
    } catch (e) {
      if (e instanceof ApiError) {
        error.value = e
      } else {
        showError(e, '调试失败')
      }
      return null
    } finally {
      running.value = false
    }
  }

  function reset(): void {
    result.value = null
    error.value = null
  }

  return { running, result, error, run, reset }
}
