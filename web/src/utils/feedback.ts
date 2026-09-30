// 统一的错误提示与确认框。契约的 error.message 和 details 都在这里显示。
import { h } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError } from '../api'

function isDialogDismiss(e: unknown): boolean {
  // ElMessageBox 被取消或关闭时以字符串 reject
  return e === 'cancel' || e === 'close'
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return String(e)
}

/** 有 details 时用对话框逐条列出；否则用消息条。 */
export function showError(e: unknown, title = '操作失败'): void {
  if (isDialogDismiss(e)) return
  if (e instanceof ApiError && e.details.length > 0) {
    void ElMessageBox.alert(
      h('div', { class: 'error-detail' }, [
        h('p', e.message),
        h(
          'ul',
          e.details.map((item) => h('li', item)),
        ),
      ]),
      title,
      { type: 'error', confirmButtonText: '知道了' },
    ).catch(() => undefined)
    return
  }
  ElMessage.error({ message: errorMessage(e), duration: 5000, showClose: true })
}

/** 确认框。确认返回 true，取消或关闭返回 false。 */
export async function confirmAction(message: string, title = '请确认', danger = false): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      confirmButtonClass: danger ? 'el-button--danger' : '',
    })
    return true
  } catch {
    return false
  }
}
