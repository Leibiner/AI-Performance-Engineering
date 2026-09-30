// 显示用的格式化函数。空值统一显示为「—」。

export const DASH = '—'

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** ISO 8601 UTC 字符串 → 本地时间 YYYY-MM-DD HH:mm:ss */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  )
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: digits })
}

export function formatCount(value: number | null | undefined): string {
  return formatNumber(value, 0)
}

/** 毫秒数，保留 1 位小数 */
export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return `${formatNumber(value, 1)} ms`
}

/** 0~1 的比例 → 百分数 */
export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return `${formatNumber(value * 100, digits)}%`
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  const units = ['B', 'KB', 'MB', 'GB']
  let n = value
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i += 1
  }
  return `${formatNumber(n, i === 0 ? 0 : 1)} ${units[i]}`
}

/** 时长（毫秒）→ 「1 分 5 秒」「8.4 秒」 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms) || ms < 0) return DASH
  if (ms < 60_000) return `${formatNumber(ms / 1000, 1)} 秒`
  const totalSec = Math.round(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  return h > 0 ? `${h} 小时 ${m} 分 ${s} 秒` : `${m} 分 ${s} 秒`
}

/** 两个 ISO 时间之间的毫秒数 */
export function elapsedMs(startIso: string, endIso: string | null | undefined, now = Date.now()): number {
  const start = new Date(startIso).getTime()
  const end = endIso ? new Date(endIso).getTime() : now
  return Math.max(0, end - start)
}

/** 比例（0~1）与百分数互转，避免 0.7 / 100 这类浮点尾数 */
export function ratioToPercent(ratio: number | null | undefined): number | undefined {
  if (ratio === null || ratio === undefined) return undefined
  return Math.round(ratio * 1e6) / 1e4
}
export function percentToRatio(percent: number | null | undefined): number | null {
  if (percent === null || percent === undefined) return null
  return Math.round(percent * 1e4) / 1e6
}
