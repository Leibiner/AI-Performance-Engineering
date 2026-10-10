import type { ApiDefInput, ApiFormItem, FileAsset, HttpMethod } from '../api'
import { METHODS } from './method'
import { splitVars } from './vars'

export interface ParsedFormItem {
  name: string
  type: 'text' | 'file'
  value: string
  /** 文件项：@ 后面的路径 */
  path?: string
}

export interface ParsedCurl {
  method: HttpMethod
  url: string
  headers: Record<string, string>
  body: string | null
  /** 有 -F / --form 时是 multipart 的各项 */
  form: ParsedFormItem[] | null
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

const DATA_FLAGS = new Set(['-d', '--data', '--data-raw', '--data-binary', '--data-ascii'])
// 带一个参数、但对接口定义没有意义的选项：跳过它和它的参数
const SKIP_WITH_ARG = new Set([
  '-o', '--output', '-w', '--write-out', '-m', '--max-time', '--connect-timeout', '--cacert', '--capath',
  '-x', '--proxy', '--retry', '--resolve', '--limit-rate', '-c', '--cookie-jar', '--cert', '--key',
])

/** 和 curl 的 --data-urlencode 一样：只保留 RFC 3986 的非保留字符，空格编码为 %20 */
function curlEscape(text: string): string {
  return encodeURIComponent(text).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)
}

/** --data-urlencode 的四种写法：content、=content、name=content 编码 content；name@file、@file 读文件（不支持） */
function urlencodeArg(arg: string): string {
  const m = /^([^=@]*)([=@])([\s\S]*)$/.exec(arg)
  if (!m) return curlEscape(arg)
  if (m[2] === '@') throw new Error(`不支持从文件读取请求体（--data-urlencode ${arg}）`)
  return m[1] ? `${m[1]}=${curlEscape(m[3])}` : curlEscape(m[3])
}

/** -F 的值可以用双引号包住（Postman、Apifox 导出的命令都这样），后面可以跟 ;type= ;filename= ;headers= */
function formValue(raw: string): string {
  if (raw.startsWith('"')) {
    let out = ''
    for (let i = 1; i < raw.length; i += 1) {
      const c = raw[i]
      if (c === '\\' && (raw[i + 1] === '\\' || raw[i + 1] === '"')) {
        out += raw[i + 1]
        i += 1
      } else if (c === '"') {
        return out
      } else {
        out += c
      }
    }
    return out
  }
  const m = /;\s*(type|filename|headers|encoder)=/i.exec(raw)
  return m ? raw.slice(0, m.index) : raw
}

function parseFormArg(flag: string, arg: string): ParsedFormItem {
  const eq = arg.indexOf('=')
  if (eq <= 0) throw new Error(`无法识别的表单项：${flag} ${arg}`)
  const name = arg.slice(0, eq)
  const rest = arg.slice(eq + 1)
  if (flag === '--form-string') return { name, type: 'text', value: rest }
  if (rest.startsWith('@')) return { name, type: 'file', value: '', path: formValue(rest.slice(1)) }
  if (rest.startsWith('<')) throw new Error(`不支持从文件读取表单值（${name}=${rest}）`)
  return { name, type: 'text', value: formValue(rest) }
}

const hasHeader = (headers: Record<string, string>, name: string) =>
  Object.keys(headers).some((k) => k.toLowerCase() === name)

/** 解析一条 curl 命令。不支持的用法（从文件读请求体、-T、HEAD）抛出带原因的 Error。 */
export function parseCurl(text: string): ParsedCurl {
  const tokens = tokenize(text.trim())
  if (tokens.length === 0) throw new Error('内容为空')
  if (!/^curl(\.exe)?$/i.test(tokens[0])) throw new Error('不是 curl 命令：要以 curl 开头')

  let method: string | null = null
  let url: string | null = null
  const headers: Record<string, string> = {}
  const data: string[] = []
  const form: ParsedFormItem[] = []
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
    } else if (t === '--data-urlencode') data.push(urlencodeArg(next(t)))
    else if (t === '--json') {
      data.push(next(t))
      json = true
    } else if (t === '-F' || t === '--form' || t === '--form-string') form.push(parseFormArg(t, next(t)))
    else if (t === '-T' || t === '--upload-file') throw new Error(`不支持 ${t}（把文件作为请求体上传）`)
    else if (t === '-u' || t === '--user') headers.Authorization = `Basic ${btoa(next(t))}`
    else if (t === '-A' || t === '--user-agent') headers['User-Agent'] = next(t)
    else if (t === '-e' || t === '--referer') headers.Referer = next(t)
    else if (t === '-b' || t === '--cookie') headers.Cookie = next(t)
    else if (t === '--url') url = next(t)
    else if (t === '-I' || t === '--head') throw new Error('不支持 HEAD 方法')
    else if (t === '-G' || t === '--get') asGet = true
    else if (SKIP_WITH_ARG.has(t)) next(t)
    else if (t.startsWith('-')) {
      // 无参数的开关（--compressed、-s、-k、-L、-i、-v、--insecure、--location …）：忽略
    } else if (url === null) url = t
    else throw new Error(`无法识别的参数：${t}`)
  }
  if (!url) throw new Error('没有找到请求地址')
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`
  if (form.length && data.length) throw new Error('-F 不能和 -d / --data 一起用')
  if (form.length && asGet) throw new Error('-F 不能和 -G 一起用')

  let body: string | null = data.length ? data.join('&') : null
  if (asGet && body !== null) {
    url += (url.includes('?') ? '&' : '?') + body
    body = null
  }
  if (json) {
    headers['Content-Type'] ??= 'application/json'
    headers.Accept ??= 'application/json'
  } else if (body !== null && !hasHeader(headers, 'content-type') && !/^\s*[[{]/.test(body)) {
    // curl 的 -d 默认就是这个类型；像 JSON 的交给引擎补 application/json
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
  }
  const m = method ?? (body !== null || form.length ? 'POST' : 'GET')
  if (!(METHODS as string[]).includes(m)) {
    throw new Error(`不支持的方法 ${m}（只支持 ${METHODS.join(' / ')}）`)
  }
  return { method: m as HttpMethod, url, headers, body, form: form.length ? form : null }
}

/** 这些请求头由 HTTP 客户端自己生成，不该存进接口定义 */
const DROP_HEADERS = new Set(['host', 'content-length', 'connection', 'accept-encoding'])

export interface CurlImport {
  input: ApiDefInput
  /** 原命令里的协议 + 主机，对应被测环境的 baseUrl */
  origin: string
  /** form-data 的文件项和原路径：导入后 fileId 为 null，要在编辑器里选已上传的文件 */
  files: { name: string; path: string }[]
}

const baseName = (path: string) => path.split(/[\\/]/).pop() || path

/** 把解析结果拆成"被测环境的地址"和"接口定义"。 */
export function curlToApi(parsed: ParsedCurl): CurlImport {
  const m = /^(https?:\/\/[^/?#]+)(.*)$/i.exec(parsed.url)
  if (!m) throw new Error(`地址不合法：${parsed.url}`)
  const origin = m[1]
  let path = m[2] || '/'
  if (!path.startsWith('/')) path = `/${path}`
  const multipart = parsed.form !== null
  const headers: Record<string, string> = {}
  for (const [k, v] of Object.entries(parsed.headers)) {
    const lower = k.toLowerCase()
    if (DROP_HEADERS.has(lower) || k.startsWith(':')) continue
    // multipart 的 Content-Type 由引擎带上 boundary 重新生成
    if (multipart && lower === 'content-type') continue
    headers[k] = v
  }
  const form: ApiFormItem[] = (parsed.form ?? []).map((item) =>
    item.type === 'file'
      ? { name: item.name, type: 'file', value: '', fileId: null }
      : { name: item.name, type: 'text', value: item.value, fileId: null },
  )
  const files = (parsed.form ?? []).filter((i) => i.type === 'file').map((i) => ({ name: i.name, path: i.path ?? '' }))
  const fileNote = files.length ? `；文件项 ${files.map((f) => `${f.name}=@${baseName(f.path)}`).join('、')}` : ''
  const pathname = path.split('?')[0]
  return {
    origin,
    files,
    input: {
      folderId: null,
      name: `${parsed.method} ${pathname}`.slice(0, 100),
      method: parsed.method,
      path,
      headers,
      bodyType: multipart ? 'multipart' : 'raw',
      body: multipart ? null : parsed.body,
      form,
      expectStatus: 200,
      expectBodyContains: null,
      extracts: [],
      note: `从 cURL 导入，原地址 ${origin}${fileNote}`,
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

/** 和引擎一样的 x-www-form-urlencoded 编码（WHATWG：空格为 +，!'()~ 也编码）；{{变量}} 原样保留 */
function formEncode(s: string): string {
  return splitVars(s)
    .map((seg) =>
      seg.name === null
        ? encodeURIComponent(seg.text)
            .replace(/[!'()~]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)
            .replace(/%20/g, '+')
        : seg.text,
    )
    .join('')
}

function shellQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`
}

/** 当前接口在所选被测环境下实际会发出的请求，写成可以直接在终端运行的 curl。变量占位符原样保留。 */
export function buildCurl(
  api: ApiDefInput,
  baseUrl: string,
  envHeaders: Record<string, string>,
  files: Pick<FileAsset, 'id' | 'name' | 'contentType'>[] = [],
): string {
  const headers = mergeHeaders(envHeaders, api.headers)
  const bodyType = api.bodyType ?? 'raw'
  const lines = [`curl -X ${api.method} ${shellQuote(baseUrl.replace(/\/+$/, '') + api.path)}`]
  const tail: string[] = []
  if (bodyType === 'raw') {
    const body = api.body && api.body !== '' ? api.body : null
    if (body !== null && !hasHeader(headers, 'content-type') && /^\s*[[{]/.test(body)) headers['Content-Type'] = 'application/json'
    if (body !== null) tail.push(`--data-raw ${shellQuote(body)}`)
  } else if (bodyType === 'form') {
    // 和引擎一样：接口自己没写 Content-Type 时，不用环境的，换成表单类型
    if (!hasHeader(api.headers ?? {}, 'content-type')) {
      for (const k of Object.keys(headers)) if (k.toLowerCase() === 'content-type') delete headers[k]
      headers['Content-Type'] = 'application/x-www-form-urlencoded'
    }
    const items = (api.form ?? []).filter((item) => item.type === 'text')
    tail.push(`--data-raw ${shellQuote(items.map((item) => `${formEncode(item.name)}=${formEncode(item.value)}`).join('&'))}`)
  } else {
    // 和引擎一样去掉合并后的 Content-Type，由 curl 生成带 boundary 的
    for (const k of Object.keys(headers)) if (k.toLowerCase() === 'content-type') delete headers[k]
    for (const item of api.form ?? []) {
      if (item.type === 'text') {
        tail.push(`--form-string ${shellQuote(`${item.name}=${item.value}`)}`)
        continue
      }
      const file = files.find((f) => f.id === item.fileId)
      const spec = file ? `@"${file.name.replace(/(["\\])/g, '\\$1')}";type=${file.contentType}` : '@文件'
      tail.push(`-F ${shellQuote(`${item.name}=${spec}`)}`)
    }
  }
  for (const [k, v] of Object.entries(headers)) lines.push(`-H ${shellQuote(`${k}: ${v}`)}`)
  lines.push(...tail)
  return lines.join(' \\\n  ')
}
