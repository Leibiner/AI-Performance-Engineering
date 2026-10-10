// 和引擎（perf/core/interp.js）相同的引用写法：{{ 名称 }}、{{$动态变量}}、{{$动态变量(参数)}}
const VAR_PATTERN = /\{\{\s*(\$?[^{}\s()]+(?:\([^{}()]*\))?)\s*\}\}/g

/** 变量名：字母（含中文）、数字、下划线。环境变量、提取规则、数据集的列、流程变量共用 */
export const VAR_NAME_PATTERN = /^[\p{L}\p{N}_]+$/u

export function isValidVarName(name: string): boolean {
  return VAR_NAME_PATTERN.test(name)
}

export interface TextSegment {
  text: string
  /** 引用里的名称（动态变量含 $ 和括号参数）；普通文本为 null */
  name: string | null
}

export function splitVars(text: string): TextSegment[] {
  const out: TextSegment[] = []
  let last = 0
  for (const m of text.matchAll(VAR_PATTERN)) {
    const start = m.index ?? 0
    if (start > last) out.push({ text: text.slice(last, start), name: null })
    out.push({ text: m[0], name: m[1] })
    last = start + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last), name: null })
  return out
}

/** 文本里引用到的名称，去重，按出现顺序 */
export function varNames(text: string): string[] {
  return [...new Set([...text.matchAll(VAR_PATTERN)].map((m) => m[1]))]
}

export function isDynamicRef(name: string): boolean {
  return name.startsWith('$')
}

export interface DynamicVar {
  name: string
  aliases?: string[]
  meaning: string
  example: string
}

/** 契约 §3.1「变量」的动态变量表 */
export const DYNAMIC_VARS: DynamicVar[] = [
  { name: '$timestamp', meaning: '当前 Unix 时间，秒', example: '{{$timestamp}}' },
  { name: '$timestampMs', meaning: '当前 Unix 时间，毫秒', example: '{{$timestampMs}}' },
  { name: '$isoTimestamp', meaning: '当前时间，ISO 8601 UTC', example: '{{$isoTimestamp}}' },
  {
    name: '$date',
    meaning: '执行机本地时间按格式输出，默认 yyyy-MM-dd；括号里的全部内容都是格式，认 yyyy MM dd HH mm ss SSS',
    example: '{{$date(yyyyMMddHHmmss)}}',
  },
  { name: '$uuid', aliases: ['$guid', '$randomUUID'], meaning: '随机 UUID v4', example: '{{$uuid}}' },
  { name: '$randomInt', meaning: '随机整数，闭区间，默认 0–1000', example: '{{$randomInt(1,100)}}' },
  { name: '$randomString', meaning: '随机字母数字串，默认长度 8，最长 256', example: '{{$randomString(16)}}' },
  { name: '$vu', meaning: '当前 VU 的编号，从 1 开始，整个测试内唯一', example: '{{$vu}}' },
  { name: '$iteration', meaning: '当前 VU 在本流程里的迭代序号，从 0 开始', example: '{{$iteration}}' },
  { name: '$runId', meaning: '运行 id（调试时是 dbg-…）', example: '{{$runId}}' },
]

const DYNAMIC_INDEX = new Map<string, DynamicVar>()
for (const d of DYNAMIC_VARS) {
  DYNAMIC_INDEX.set(d.name, d)
  for (const a of d.aliases ?? []) DYNAMIC_INDEX.set(a, d)
}

/** 去掉括号参数后按名称（含别名）查动态变量表；不认识返回 null */
export function dynamicVar(name: string): DynamicVar | null {
  const base = name.replace(/\(.*$/, '')
  return DYNAMIC_INDEX.get(base) ?? null
}

const NO_ARGS = new Set(['$timestamp', '$timestampMs', '$isoTimestamp', '$uuid', '$guid', '$randomUUID', '$vu', '$iteration', '$runId'])

function safeInt(s: string): number | null {
  if (!/^-?\d+$/.test(s)) return null
  const n = Number(s)
  return Number.isSafeInteger(n) ? n : null
}

/** 参数是否符合引擎的规则（perf/core/interp.js 的 DYNAMIC、server/variables.py）；没问题返回 null */
export function dynamicArgProblem(name: string): string | null {
  const m = /^(\$[A-Za-z]+)(?:\(([^{}()]*)\))?$/.exec(name)
  if (!m || !DYNAMIC_INDEX.has(m[1])) return null
  const raw = (m[2] ?? '').trim()
  const args = raw === '' ? [] : raw.split(',').map((a) => a.trim())
  if (m[1] === '$date' || args.length === 0) return null
  if (NO_ARGS.has(m[1])) return `${m[1]} 不接受参数`
  if (m[1] === '$randomInt') {
    const [low, high] = args.length === 2 ? [safeInt(args[0]), safeInt(args[1])] : [null, null]
    return low === null || high === null || low > high ? '$randomInt 的参数是 (最小,最大)，两个整数且最小不大于最大' : null
  }
  const len = args.length === 1 ? safeInt(args[0]) : null
  return len === null || len < 1 || len > 256 ? '$randomString 的参数是长度，1–256 之间的整数' : null
}

/** VarInput 里括号的着色：有值 / 待提取 / 未定义 / 不确定（如没有选调试环境时的环境变量） */
export type VarState = 'is-known' | 'is-extracted' | 'is-unknown' | 'is-unsure'

export interface VarResolution {
  state: VarState
  title: string
}
