import type { Slo } from '../api'
import { formatNumber, formatPercent } from './format'

/** 把验收标准写成几条短句，用于表格显示。 */
export function sloItems(slo: Slo | null | undefined): string[] {
  if (!slo) return []
  const items: string[] = []
  if (slo.p95Ms !== null && slo.p95Ms !== undefined) items.push(`p95 < ${formatNumber(slo.p95Ms)} ms`)
  if (slo.p99Ms !== null && slo.p99Ms !== undefined) items.push(`p99 < ${formatNumber(slo.p99Ms)} ms`)
  if (slo.errorRate !== null && slo.errorRate !== undefined) items.push(`错误率 < ${formatPercent(slo.errorRate)}`)
  if (slo.checksRate !== null && slo.checksRate !== undefined) items.push(`检查通过率 ≥ ${formatPercent(slo.checksRate)}`)
  return items
}
