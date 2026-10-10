// fetch 封装：统一拼接 /api 前缀、序列化 JSON、把契约的错误格式转成 ApiError。

const BASE = '/api'

/** 契约 §3 的错误响应：{ error: { code, message, details? } } */
export class ApiError extends Error {
  /** HTTP 状态码；0 表示请求没有到达后端 */
  readonly status: number
  readonly code: string
  readonly details: string[]

  constructor(status: number, code: string, message: string, details: string[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>

interface RequestOptions {
  query?: Query
  body?: unknown
  accept?: string
}

function buildUrl(path: string, query?: Query): string {
  if (!query) return BASE + path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${BASE}${path}?${qs}` : BASE + path
}

function toStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : []
}

/** 把非 2xx 响应体解析成 ApiError。优先按契约格式；兼容 FastAPI 默认的 { detail }。 */
function parseError(status: number, data: unknown): ApiError {
  const fallback = `请求失败（HTTP ${status}）`
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>
    const err = obj.error
    if (err && typeof err === 'object') {
      const e = err as Record<string, unknown>
      return new ApiError(
        status,
        typeof e.code === 'string' ? e.code : `HTTP_${status}`,
        typeof e.message === 'string' && e.message ? e.message : fallback,
        toStringList(e.details),
      )
    }
    const detail = obj.detail
    if (typeof detail === 'string') return new ApiError(status, `HTTP_${status}`, detail)
    if (Array.isArray(detail)) {
      const details = detail.map((item) => {
        if (item && typeof item === 'object') {
          const d = item as { loc?: unknown[]; msg?: unknown }
          const loc = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body').join('.') : ''
          return loc ? `${loc}：${String(d.msg ?? '')}` : String(d.msg ?? '')
        }
        return String(item)
      })
      return new ApiError(status, `HTTP_${status}`, fallback, details)
    }
  }
  return new ApiError(status, `HTTP_${status}`, fallback)
}

async function send(method: string, path: string, options: RequestOptions): Promise<Response> {
  const init: RequestInit = { method, headers: { Accept: options.accept ?? 'application/json' } }
  if (options.body !== undefined) {
    init.headers = { ...init.headers, 'Content-Type': 'application/json' }
    init.body = JSON.stringify(options.body)
  }
  try {
    return await fetch(buildUrl(path, options.query), init)
  } catch {
    throw new ApiError(0, 'NETWORK', '无法连接后端服务，请确认服务已启动')
  }
}

export async function request<T>(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const res = await send(method, path, options)
  const text = res.status === 204 ? '' : await res.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }
  if (!res.ok) throw parseError(res.status, data)
  return data as T
}

/** 读取文本类响应（如 k6.log、数据集导出的 CSV）。按 UTF-8 解码。 */
export async function requestText(path: string, query?: Query): Promise<string> {
  const res = await send('GET', path, { query, accept: 'text/plain, text/csv, */*' })
  const text = await res.text()
  if (!res.ok) {
    let data: unknown = null
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
    throw parseError(res.status, data)
  }
  return text
}

/** 给 <a href>、<iframe src> 用的接口地址。 */
export function apiUrl(path: string): string {
  return BASE + path
}
