// 调试结果的展示辅助：步骤状态、JSON 美化、检查汇总。
import type { DebugStep, DebugStepStatus } from '../api'

export interface StepStatusMeta {
  label: string
  tag: 'success' | 'danger' | 'info' | 'warning'
}

export const STEP_STATUS: Record<DebugStepStatus, StepStatusMeta> = {
  passed: { label: '通过', tag: 'success' },
  failed: { label: '未通过', tag: 'danger' },
  error: { label: '出错', tag: 'danger' },
  skipped: { label: '未执行', tag: 'info' },
}

/** 能解析成 JSON 就返回缩进后的文本，否则 null。 */
export function tryPrettyJson(text: string | null | undefined): string | null {
  if (!text) return null
  const head = text.trimStart()[0]
  if (head !== '{' && head !== '[') return null
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return null
  }
}

export function checksSummary(step: DebugStep): { passed: number; total: number } {
  const total = step.checks.length
  const passed = step.checks.filter((c) => c.ok).length
  return { passed, total }
}

/** 响应体长度（字符数）→ 便于阅读的大小。字符数和字节数接近，标为"约"。 */
export function formatChars(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n < 1024) return `${n} 字符`
  if (n < 1024 * 1024) return `约 ${(n / 1024).toFixed(1)} KB`
  return `约 ${(n / 1024 / 1024).toFixed(2)} MB`
}
