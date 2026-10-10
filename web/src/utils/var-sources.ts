import type { ApiDefInput } from '../api'
import { mergeHeaders } from './curl'
import { dynamicArgProblem, dynamicVar, isDynamicRef, varNames, type VarResolution } from './vars'

type RefSource = Pick<ApiDefInput, 'path' | 'headers' | 'bodyType' | 'body' | 'form' | 'expectBodyContains'>

/** 契约 §3.2 第 8 条检查的位置：path、合并后的请求头的值、body（raw）或 form 的名称和文本值、expectBodyContains */
export function apiRefTexts(api: RefSource, envHeaders: Record<string, string> = {}): string[] {
  const texts = [api.path, ...Object.values(mergeHeaders(envHeaders, api.headers ?? {}))]
  if ((api.bodyType ?? 'raw') === 'raw') {
    texts.push(api.body ?? '')
  } else {
    for (const item of api.form ?? []) {
      texts.push(item.name)
      if (item.type === 'text') texts.push(item.value)
    }
  }
  texts.push(api.expectBodyContains ?? '')
  return texts
}

/** 按出现顺序去重；逐段匹配，避免引用跨两个字段拼起来 */
export function refsOf(texts: string[]): string[] {
  const out = new Set<string>()
  for (const t of texts) for (const n of varNames(t)) out.add(n)
  return [...out]
}

export function apiRefs(api: RefSource, envHeaders: Record<string, string> = {}): string[] {
  return refsOf(apiRefTexts(api, envHeaders))
}

/**
 * 分开接口自己的引用和只来自被测环境公共请求头的引用（接口没有用同名请求头覆盖的那些），
 * 两者的检查规则不同（契约 §3.2 第 8 条）。multipart 时引擎换掉 Content-Type，不检查它
 */
function splitRefs(api: RefSource, envHeaders: Record<string, string>): { own: string[]; inherited: string[] } {
  const multipart = api.bodyType === 'multipart'
  const ownNames = new Set(Object.keys(api.headers ?? {}).map((n) => n.toLowerCase()))
  const ownTexts = [api.path]
  const envTexts: string[] = []
  for (const [name, value] of Object.entries(mergeHeaders(envHeaders, api.headers ?? {}))) {
    // multipart 时引擎换掉 Content-Type；x-www-form-urlencoded 时接口自己没写，引擎也会丢掉环境的
    if (name.toLowerCase() === 'content-type' && (multipart || (api.bodyType === 'form' && !ownNames.has('content-type')))) continue
    ;(ownNames.has(name.toLowerCase()) ? ownTexts : envTexts).push(value)
  }
  if ((api.bodyType ?? 'raw') === 'raw') {
    ownTexts.push(api.body ?? '')
  } else {
    for (const item of api.form ?? []) {
      ownTexts.push(item.name)
      if (item.type === 'text') ownTexts.push(item.value)
    }
  }
  ownTexts.push(api.expectBodyContains ?? '')
  const own = refsOf(ownTexts)
  return { own, inherited: refsOf(envTexts).filter((n) => !own.includes(n)) }
}

interface StepApi extends RefSource {
  name: string
  extracts: { var: string }[]
}

export interface FlowVarModel {
  /** 被测环境（只看初始值）；null 表示没有选，环境变量这一层未知 */
  env: { name: string; variables: Record<string, string>; headers: Record<string, string> } | null
  datasets: { name: string; columns: string[] }[]
  variables: { name: string; value: string }[]
  /** 还没选接口的步骤为 null */
  initSteps: (StepApi | null)[]
  steps: (StepApi | null)[]
  /** 全部已保存接口，只用于"能提取它的接口不在本流程里"的提示 */
  allApis: StepApi[]
}

export type RefPosition = { kind: 'variable' | 'init' | 'main'; index: number }
export type RefState = 'ok' | 'missing' | 'unsure'

export interface RefCheck {
  name: string
  state: RefState
  title: string
  /** 只来自被测环境的公共请求头 */
  fromEnvHeader?: boolean
}

export interface StepVars {
  uses: RefCheck[]
  produces: string[]
}

export interface FlowVarReport {
  variables: RefCheck[][]
  init: (StepVars | null)[]
  main: (StepVars | null)[]
  /** 没有来源的引用，一处一条 */
  problems: string[]
}

const has = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k)
const extractsVar = (api: StepApi | null, name: string) => !!api?.extracts?.some((e) => e.var.trim() === name)

function stepLabel(kind: 'init' | 'main', index: number, api: StepApi | null): string {
  const name = api ? `「${api.name}」` : ''
  return kind === 'init' ? `初始化第 ${index + 1} 步${name}` : `第 ${index + 1} 步${name}`
}

/** 有来源时按覆盖顺序列出（后写的覆盖先写的，所以生效的排在最前） */
function sourcesOf(model: FlowVarModel, pos: RefPosition, name: string): string[] {
  const out: string[] = []
  if (pos.kind === 'main') {
    for (let k = pos.index - 1; k >= 0; k -= 1) {
      if (extractsVar(model.steps[k], name)) {
        out.push(`由${stepLabel('main', k, model.steps[k])}提取`)
        break
      }
    }
  }
  const initLimit = pos.kind === 'init' ? pos.index : pos.kind === 'main' ? model.initSteps.length : 0
  for (let k = initLimit - 1; k >= 0; k -= 1) {
    if (extractsVar(model.initSteps[k], name)) {
      out.push(`由${stepLabel('init', k, model.initSteps[k])}提取`)
      break
    }
  }
  const varLimit = pos.kind === 'variable' ? pos.index : model.variables.length
  if (model.variables.slice(0, varLimit).some((v) => v.name.trim() === name)) out.push('流程变量')
  for (const d of model.datasets) if (d.columns.includes(name)) out.push(`数据集「${d.name}」的列`)
  if (model.env && has(model.env.variables, name)) out.push(`被测环境「${model.env.name}」的变量`)
  return out
}

/** 没有来源时的线索：流程里排在后面的产出、或不在本流程里的接口 */
function missingHint(model: FlowVarModel, pos: RefPosition, name: string): string {
  if (pos.kind === 'variable') {
    const later = model.variables.findIndex((v, i) => i >= pos.index && v.name.trim() === name)
    if (later === pos.index) return '不能引用自己'
    if (later > pos.index) return `流程变量 ${name} 排在后面`
  }
  if (pos.kind !== 'variable' && extractsVar((pos.kind === 'init' ? model.initSteps : model.steps)[pos.index], name)) {
    return '这一步自己的提取不算这一步的来源'
  }
  const inFlow: [kind: 'init' | 'main', list: (StepApi | null)[]][] = [
    ['init', model.initSteps],
    ['main', model.steps],
  ]
  for (const [kind, list] of inFlow) {
    const k = list.findIndex((api) => extractsVar(api, name))
    if (k >= 0) return `${stepLabel(kind, k, list[k])}提取它，但排在后面`
  }
  const outside = model.allApis.filter((api) => extractsVar(api, name)).map((api) => `「${api.name}」`)
  if (outside.length) return `接口${outside.slice(0, 3).join('、')}能提取它，但不在本流程里`
  return ''
}

export function resolveRef(model: FlowVarModel, pos: RefPosition, name: string): RefCheck {
  if (isDynamicRef(name)) {
    const d = dynamicVar(name)
    if (!d) return { name, state: 'missing', title: '不是内置的动态变量' }
    const problem = dynamicArgProblem(name)
    return problem ? { name, state: 'missing', title: `参数不对：${problem}` } : { name, state: 'ok', title: `动态变量：${d.meaning}` }
  }
  const sources = sourcesOf(model, pos, name)
  if (sources.length) return { name, state: 'ok', title: sources.join('；') }
  const hint = missingHint(model, pos, name)
  if (!model.env) {
    return { name, state: 'unsure', title: ['没有选择调试环境，不确定是否是环境变量', hint].filter(Boolean).join('；') }
  }
  const base = `没有来源：被测环境「${model.env.name}」没有这个变量，数据集、流程变量和前面的步骤也不产出它`
  return { name, state: 'missing', title: hint ? `${base}（${hint}）` : base }
}

/**
 * 公共请求头每一步都带。常见写法是 Authorization: Bearer {{token}}、token 由登录提取：登录这一步发出的是未替换的原文，
 * 服务端不看，所以只要求流程里某一处产出它，不要求排在这一步前面
 */
function resolveHeaderRef(model: FlowVarModel, pos: RefPosition, name: string): RefCheck {
  const strict = resolveRef(model, pos, name)
  if (strict.state === 'ok' || isDynamicRef(name)) return { ...strict, title: `公共请求头；${strict.title}`, fromEnvHeader: true }
  const lists: [kind: 'init' | 'main', list: (StepApi | null)[]][] = [
    ['init', model.initSteps],
    ['main', model.steps],
  ]
  for (const [kind, list] of lists) {
    const k = list.findIndex((api) => extractsVar(api, name))
    if (k >= 0) {
      return { name, state: 'ok', title: `公共请求头；由${stepLabel(kind, k, list[k])}提取，在那之前原样发出`, fromEnvHeader: true }
    }
  }
  if (!model.env) return { ...strict, title: `公共请求头；${strict.title}`, fromEnvHeader: true }
  return {
    name,
    state: 'missing',
    title: '没有来源：被测环境没有这个变量，这个流程的数据集、流程变量和步骤也都不产出它',
    fromEnvHeader: true,
  }
}

const TO_VAR_STATE = { ok: 'is-known', missing: 'is-unknown', unsure: 'is-unsure' } as const

export function refResolver(model: FlowVarModel, pos: RefPosition): (name: string) => VarResolution {
  return (name) => {
    const r = resolveRef(model, pos, name)
    return { state: TO_VAR_STATE[r.state], title: `${name}：${r.title}` }
  }
}

function stepVars(model: FlowVarModel, kind: 'init' | 'main', index: number, api: StepApi | null): StepVars | null {
  if (!api) return null
  const { own, inherited } = splitRefs(api, model.env?.headers ?? {})
  const uses = [
    ...own.map((n) => resolveRef(model, { kind, index }, n)),
    ...inherited.map((n) => resolveHeaderRef(model, { kind, index }, n)),
  ]
  const produces = [...new Set(api.extracts.map((e) => e.var.trim()).filter(Boolean))]
  return { uses, produces }
}

export function analyzeFlow(model: FlowVarModel): FlowVarReport {
  const variables = model.variables.map((v, index) =>
    refsOf([v.value]).map((n) => resolveRef(model, { kind: 'variable', index }, n)),
  )
  const init = model.initSteps.map((api, i) => stepVars(model, 'init', i, api))
  const main = model.steps.map((api, i) => stepVars(model, 'main', i, api))
  const problems: string[] = []
  const headerMissing = new Map<string, RefCheck>()
  const report = (where: string, checks: RefCheck[]) => {
    for (const c of checks) {
      if (c.state !== 'missing') continue
      // 公共请求头每一步都带，缺的只报一次
      if (c.fromEnvHeader) headerMissing.set(c.name, c)
      else problems.push(`${where}引用了 {{${c.name}}}，但${c.title}`)
    }
  }
  variables.forEach((checks, i) => report(`流程变量 ${model.variables[i].name.trim() || `#${i + 1}`} `, checks))
  init.forEach((s, i) => s && report(stepLabel('init', i, model.initSteps[i]), s.uses))
  main.forEach((s, i) => s && report(stepLabel('main', i, model.steps[i]), s.uses))
  for (const c of headerMissing.values()) {
    problems.push(`使用的被测环境「${model.env?.name ?? ''}」公共请求头引用了 {{${c.name}}}，但${c.title}`)
  }
  return { variables, init, main, problems }
}
