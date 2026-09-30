import { h, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, runsApi, systemApi, type Environment, type RunStartInput } from '../api'
import { showError } from '../utils/feedback'

/** 发起前需要知道的被测环境信息：类型为生产时要二次确认 */
export type StartEnv = Pick<Environment, 'name' | 'baseUrl' | 'type'>

interface StartOptions {
  /** 这次运行的被测环境。类型为 prod 时先弹二次确认，确认后请求里带 confirmProd: true */
  env?: StartEnv | null
  /** 预检被拒绝（422）时的处理；不传则用对话框逐条显示 details */
  onPreflightRejected?: (error: ApiError) => void
}

/** 发起运行：成功跳到运行详情；422 逐条显示原因；409 提示已有运行在进行。 */
export function useStartRun() {
  const router = useRouter()
  const starting = ref(false)

  async function confirmProd(env: StartEnv): Promise<boolean> {
    try {
      await ElMessageBox.confirm(
        h('div', { class: 'prod-confirm' }, [
          h('p', { class: 'prod-confirm-lead' }, '你正在对生产环境发起压测'),
          h('dl', [
            h('dt', '被测环境'),
            h('dd', env.name),
            h('dt', '地址'),
            h('dd', { class: 'mono' }, env.baseUrl),
          ]),
          h('p', '请求会真实地发往这个地址。请确认已获得许可，并且负载配置在安全上限以内。'),
        ]),
        '确认对生产环境压测',
        {
          type: 'warning',
          confirmButtonText: '确认，对生产环境发起压测',
          cancelButtonText: '取消',
          confirmButtonClass: 'el-button--danger',
          // 不自动聚焦到确认按钮，避免一按回车就确认
          autofocus: false,
        },
      )
      return true
    } catch {
      return false
    }
  }

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
    const payload: RunStartInput = { ...input }
    // 非生产不带 confirmProd
    delete payload.confirmProd
    if (options.env?.type === 'prod') {
      if (!(await confirmProd(options.env))) return false
      payload.confirmProd = true
    }

    starting.value = true
    try {
      const run = await runsApi.start(payload)
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
