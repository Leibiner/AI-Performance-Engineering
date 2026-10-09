// HTTP 状态码的分级与颜色：响应面板里一眼看出 2xx / 3xx / 4xx / 5xx / 没有响应。

export type StatusKind = 'success' | 'redirect' | 'client' | 'server' | 'none'

export function statusKind(status: number | null | undefined): StatusKind {
  if (!status) return 'none'
  if (status < 300) return 'success'
  if (status < 400) return 'redirect'
  if (status < 500) return 'client'
  return 'server'
}

export const STATUS_STYLE: Record<StatusKind, { color: string; soft: string }> = {
  success: { color: '#1f8a3b', soft: '#e6f4ea' },
  redirect: { color: '#2f6fd6', soft: '#e8f0fc' },
  client: { color: '#d9730d', soft: '#fdf0e1' },
  server: { color: '#d03b3b', soft: '#fbe9e9' },
  none: { color: '#6b7280', soft: '#eceef1' },
}

export function statusLabel(status: number | null | undefined, statusText?: string | null): string {
  if (!status) return '没有响应'
  const text = (statusText ?? '').replace(/^\d+\s*/, '')
  return text ? `${status} ${text}` : String(status)
}
