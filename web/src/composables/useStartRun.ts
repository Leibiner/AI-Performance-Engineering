import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, runsApi, systemApi, type RunStartInput } from '../api'
import { showError } from '../utils/feedback'

interface StartOptions {
  /** 预检被拒绝（422）时的处理；不传则用对话框逐条显示 details */
  onPreflightRejected?: (error: ApiError) => void
}

/** 发起运行：成功跳到运行详情；422 逐条显示原因；409 提示已有运行在进行。 */
export function useStartRun() {
  const router = useRouter()
  const starting = ref(false)

  async function handleConflict(error: ApiError): Promise<void> {
    let runningRunId: string | null = null
    try {
      runningRunId = (await systemApi.get()).runningRunId
    } catch {
      runningRunId = null
    }
    if (!runningRunId) {
      ElMessage.warning(error.message || '已有运行在进行中，请等它结束后再发起')
      return
    }
    try {
      await ElMessageBox.confirm(
        `${error.message || '已有运行在进行中'}。同一时间只允许 1 个运行，请等它结束或先停止它。`,
        '已有运行在进行',
        { type: 'warning', confirmButtonText: '查看正在进行的运行', cancelButtonText: '关闭' },
      )
      await router.push(`/runs/${runningRunId}`)
    } catch {
      // 用户选择关闭
    }
  }

  async function start(input: RunStartInput, options: StartOptions = {}): Promise<boolean> {
    starting.value = true
    try {
      const run = await runsApi.start(input)
      ElMessage.success('运行已发起')
      await router.push(`/runs/${run.runId}`)
      return true
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        await handleConflict(e)
      } else if (e instanceof ApiError && e.status === 422 && options.onPreflightRejected) {
        options.onPreflightRejected(e)
      } else if (e instanceof ApiError && e.status === 422) {
        showError(e, '预检未通过，没有发起运行')
      } else {
        showError(e, '发起运行失败')
      }
      return false
    } finally {
      starting.value = false
    }
  }

  return { starting, start }
}
