// cURL 命令 ↔ 接口定义。导入：从浏览器开发者工具 / Postman / Apifox 复制的 curl 填进表单；
// 导出：把当前接口在所选被测环境下实际会发的请求写成 curl，方便在终端里复现。
import type { ApiDefInput, HttpMethod } from '../api'
import { METHODS } from './method'

export interface ParsedCurl {
  method: HttpMethod
  url: string
  headers: Record<string, string>
  body: string | null
}

/** 按 shell 的规则切词：处理单引号、双引号、$'…'、反斜杠，以及行尾的续行符。 */
function tokenize(text: string): string[] {
  const src = text
    .replace(/\\\r?\n/g, ' ') // bash 续行
    .replace(/\^\r?\n/g, ' ') // Windows cmd 续行
    .replace(/\r?\n/g, ' ')
  const tokens: string[] = []
  let i = 0
  while (i < src.length) {
    const c = src[i]
    if (c === ' ' || c === '\t') {
      i += 1
      continue
    }
    let tok = ''
    while (i < src.length) {
      const ch = src[i]
      if (ch === ' ' || ch === '\t') break
      if (ch === "'") {
        const end = src.indexOf("'", i + 1)
        if (end < 0) throw new Error('单引号没有闭合')
        tok += src.slice(i + 1, end)
        i = end + 1
        continue
      }
      if (ch === '$' && src[i + 1] === "'") {
        let j = i + 2
        let out = ''
        while (j < src.length && src[j] !== "'") {
          if (src[j] === '\\' && j + 1 < src.length) {
            const n = src[j + 1]
            out += n === 'n' ? '\n' : n === 't' ? '\t' : n === 'r' ? '\r' : n
            j += 2
          } else {
            out += src[j]
            j += 1
          }
        }
        if (j >= src.length) throw new Error("$'…' 没有闭合")
        tok += out
        i = j + 1
        continue
      }
      if (ch === '"') {
        let j = i + 1
        let out = ''
        while (j < src.length && src[j] !== '"') {
          if (src[j] === '\\' && j + 1 < src.length && '"\\$`'.includes(src[j + 1])) {
            out += src[j + 1]
            j += 2
          } else {
            out += src[j]
            j += 1
          }
        }
        if (j >= src.length) throw new Error('双引号没有闭合')
        tok += out
        i = j + 1
        continue
      }
      if (ch === '\\' && i + 1 < src.length) {
        tok += src[i + 1]
        i += 2
        continue
      }
      tok += ch
      i += 1
    }
    tokens.push(tok)
  }
  return tokens
}

const DATA_FLAGS = new Set(['-d', '--data', '--data-raw', '--data-binary', '--data-ascii', '--data-urlencode'])
// 带一个参数、但对接口定义没有意义的选项：跳过它和它的参数
const SKIP_WITH_ARG = new Set([
  '-o', '--output', '-w', '--write-out', '-m', '--max-time', '--connect-timeout', '--cacert', '--capath',
  '-x', '--proxy', '--retry', '--resolve', '-T', '--upload-file', '--limit-rate', '-c', '--cookie-jar', '--cert', '--key',
])

/** 解析一条 curl 命令。不支持的用法（文件、multipart、HEAD）抛出带原因的 Error。 */
export function parseCurl(text: string): ParsedCurl {
  const tokens = tokenize(text.trim())
  if (tokens.length === 0) throw new Error('内容为空')
  if (!/^curl(\.exe)?$/i.test(tokens[0])) throw new Error('不是 curl 命令：要以 curl 开头')

  let method: string | null = null
  let url: string | null = null
  const headers: Record<string, string> = {}
  const data: string[] = []
  let json = false
  let asGet = false

  let i = 1
  const next = (flag: string): string => {
    if (i + 1 >= tokens.length) throw new Error(`${flag} 后面缺少参数`)
    i += 1
    return tokens[i]
  }
  for (; i < tokens.length; i += 1) {
    const t = tokens[i]
    if (t === '-X' || t === '--request') method = next(t).toUpperCase()
    else if (/^-X[A-Za-z]+$/.test(t)) method = t.slice(2).toUpperCase()
    else if (t === '-H' || t === '--header') {
      const h = next(t)
      const k = h.indexOf(':')
      if (k > 0) headers[h.slice(0, k).trim()] = h.slice(k + 1).trim()
    } else if (DATA_FLAGS.has(t)) {
      const v = next(t)
      if (v.startsWith('@') && t !== '--data-raw') throw new Error(`不支持从文件读取请求体（${v}）`)
      data.push(v)
    } else if (t === '--json') {
      data.push(next(t))
      json = true
    } else if (t === '-u' || t === '--user') headers.Authorization = `Basic ${btoa(next(t))}`
    else if (t === '-A' || t === '--user-agent') headers['User-Agent'] = next(t)
    else if (t === '-e' || t === '--referer') headers.Referer = next(t)
    else if (t === '-b' || t === '--cookie') headers.Cookie = next(t)
    else if (t === '--url') url = next(t)
    else if (t === '-F' || t === '--form' || t === '--form-string') {
      throw new Error('不支持 multipart 表单（-F）：本项目的请求体只支持文本')
    } else if (t === '-I' || t === '--head') throw new Error('不支持 HEAD 方法')
    else if (t === '-G' || t === '--get') asGet = true
    else if (SKIP_WITH_ARG.has(t)) next(t)
    else if (t.startsWith('-')) {
      // 无参数的开关（--compressed、-s、-k、-L、-i、-v、--insecure、--location …）：忽略
    } else if (url === null) url = t
    else throw new Error(`无法识别的参数：${t}`)
  }
  if (!url) throw new Error('没有找到请求地址')
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`

  let body: string | null = data.length ? data.join('&') : null
  if (asGet && body !== null) {
    url += (url.includes('?') ? '&' : '?') + body
    body = null
  }
  if (json) {
    headers['Content-Type'] ??= 'application/json'
    headers.Accept ??= 'application/json'
  }
  const m = method ?? (body !== null ? 'POST' : 'GET')
  if (!(METHODS as string[]).includes(m)) {
    throw new Error(`不支持的方法 ${m}（只支持 ${METHODS.join(' / ')}）`)
  }
  return { method: m as HttpMethod, url, headers, body }
}

/** 这些请求头由 HTTP 客户端自己生成，不该存进接口定义 */
const DROP_HEADERS = new Set(['host', 'content-length', 'connection', 'accept-encoding'])

export interface CurlImport {
  input: ApiDefInput
  /** 原命令里的协议 + 主机，对应被测环境的 baseUrl */
  origin: string
}

/** 把解析结果拆成"被测环境的地址"和"接口定义"。 */
export function curlToApi(parsed: ParsedCurl): CurlImport {
  const m = /^(https?:\/\/[^/?#]+)(.*)$/i.exec(parsed.url)
  if (!m) throw new Error(`地址不合法：${parsed.url}`)
  const origin = m[1]
  let path = m[2] || '/'
  if (!path.startsWith('/')) path = `/${path}`
  const headers: Record<string, string> = {}
  for (const [k, v] of Object.entries(parsed.headers)) {
    if (!DROP_HEADERS.has(k.toLowerCase()) && !k.startsWith(':')) headers[k] = v
  }
  const pathname = path.split('?')[0]
  return {
    origin,
    input: {
      name: `${parsed.method} ${pathname}`.slice(0, 100),
      method: parsed.method,
      path,
      headers,
      body: parsed.body,
      expectStatus: 200,
      expectBodyContains: null,
      extracts: [],
      note: `从 cURL 导入，原地址 ${origin}`,
    },
  }
}

/** 和执行引擎相同的合并规则：被测环境的请求头在前，接口的在后，名称不区分大小写，后者覆盖前者。 */
export function mergeHeaders(envHeaders: Record<string, string>, apiHeaders: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  const index: Record<string, string> = {}
  for (const src of [envHeaders, apiHeaders]) {
    for (const [name, value] of Object.entries(src)) {
      const lower = name.toLowerCase()
      if (index[lower] !== undefined) delete out[index[lower]]
      index[lower] = name
      out[name] = value
    }
  }
  return out
}

function shellQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`
}

/** 当前接口在所选被测环境下实际会发出的请求，写成可以直接在终端运行的 curl。变量占位符原样保留。 */
export function buildCurl(api: ApiDefInput, baseUrl: string, envHeaders: Record<string, string>): string {
  const headers = mergeHeaders(envHeaders, api.headers)
  const body = api.body && api.body !== '' ? api.body : null
  const hasContentType = Object.keys(headers).some((k) => k.toLowerCase() === 'content-type')
  if (body !== null && !hasContentType && /^\s*[[{]/.test(body)) headers['Content-Type'] = 'application/json'
  const lines = [`curl -X ${api.method} ${shellQuote(baseUrl.replace(/\/+$/, '') + api.path)}`]
  for (const [k, v] of Object.entries(headers)) lines.push(`-H ${shellQuote(`${k}: ${v}`)}`)
  if (body !== null) lines.push(`--data-raw ${shellQuote(body)}`)
  return lines.join(' \\\n  ')
}
