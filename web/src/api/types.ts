// 与 docs/plans/mvp-contract.md 对应的类型。字段名、取值以契约为准。

/** 所有定义类资源都带的字段（契约 §3.1）。 */
export interface Stamped {
  id: number
  createdAt: string
  updatedAt: string
}

// ---------- 执行机（契约 §3.3） ----------

/** 执行机：安装了本项目、实际运行 k6 的机器。目前只有本机一台，没有新增和删除。 */
export interface Executor extends Stamped {
  name: string
  kind: 'local' | string
  note: string
  // 以下字段每次请求时实时采集，取不到的为 null
  host: string | null
  ip: string | null
  os: string | null
  arch: string | null
  cpuCores: number | null
  memTotalMb: number | null
  memAvailableMb: number | null
  loadAvg1: number | null
  diskFreeGb: number | null
  k6Version: string | null
  k6Path: string | null
  pythonVersion: string | null
  uvVersion: string | null
  projectDir: string | null
  resultsDir: string | null
  dataDir: string | null
  status: 'idle' | 'running'
  runningRunId: string | null
}
/** PUT 只能改这两项 */
export interface ExecutorInput {
  name: string
  note: string
}

// ---------- 被测环境 ----------

/** 被测环境的类型：开发 / 测试 / 预发 / 生产 */
export type EnvType = 'dev' | 'test' | 'staging' | 'prod'

export interface EnvironmentInput {
  name: string
  type: EnvType
  baseUrl: string
  headers: Record<string, string>
  // 安全上限：保护被测环境的护栏，不是负载配置。null 表示不限制；type 为 prod 时三项必填
  maxVus: number | null
  /** 每秒迭代数 */
  maxRate: number | null
  maxDurationSec: number | null
  note: string
}
export type Environment = EnvironmentInput & Stamped

// ---------- 文件夹（接口的分组，可嵌套） ----------

export interface FolderInput {
  name: string
  /** 上级文件夹；null 表示顶层 */
  parentId: number | null
  note: string
}
export type Folder = FolderInput & Stamped

// ---------- 接口 ----------

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
export type ExtractFrom = 'json' | 'regex' | 'header'

export interface Extract {
  var: string
  from: ExtractFrom
  expr: string
}

export interface ApiDefInput {
  /** 所属文件夹；null 表示根目录 */
  folderId: number | null
  name: string
  method: HttpMethod
  path: string
  headers: Record<string, string>
  body: string | null
  expectStatus: number
  expectBodyContains: string | null
  extracts: Extract[]
  note: string
}
export type ApiDef = ApiDefInput & Stamped

// ---------- 业务流程 ----------

export interface FlowStepInput {
  apiId: number
  thinkTimeMs: number
}
/** GET 返回时额外带的只读字段 */
export interface FlowStep extends FlowStepInput {
  apiName?: string
  method?: HttpMethod
  path?: string
}
export interface FlowInput {
  name: string
  note: string
  steps: FlowStepInput[]
}
export interface Flow extends Stamped {
  name: string
  note: string
  steps: FlowStep[]
}

// ---------- 负载配置 ----------

export type ProfileType = 'smoke' | 'average' | 'stress' | 'spike' | 'soak' | 'breakpoint'
export type LoadModel = 'closed' | 'open'

/** closed / 固定迭代数 → shared-iterations */
export interface SharedIterationsConfig {
  vus: number
  iterations: number
  maxDurationSec: number
}
/** closed / 固定并发 → constant-vus */
export interface ConstantVusConfig {
  vus: number
  durationSec: number
}
/** open / 固定到达率 → constant-arrival-rate */
export interface ConstantRateConfig {
  rate: number
  durationSec: number
  preAllocatedVus: number
}
export interface RateStage {
  target: number
  durationSec: number
}
/** open / 阶梯到达率 → ramping-arrival-rate */
export interface RampingRateConfig {
  startRate: number
  stages: RateStage[]
  preAllocatedVus: number
}
export type ProfileConfig =
  | SharedIterationsConfig
  | ConstantVusConfig
  | ConstantRateConfig
  | RampingRateConfig

export interface ProfileInput {
  name: string
  type: ProfileType
  model: LoadModel
  config: ProfileConfig
  note: string
}
export type Profile = ProfileInput & Stamped

// ---------- 测试 ----------

export interface Slo {
  p95Ms: number | null
  p99Ms: number | null
  /** 0~1 的比例 */
  errorRate: number | null
  /** 0~1 的比例。为 null 时执行引擎仍按默认下限 0.99 做有效性检查 */
  checksRate: number | null
}
export interface TestFlowInput {
  flowId: number
  weight: number
}
export interface TestFlow extends TestFlowInput {
  flowName?: string
}
export interface TestInput {
  name: string
  note: string
  flows: TestFlowInput[]
  slo: Slo
}
export interface LastRun {
  runId: string
  verdict: Verdict | null
  startedAt: string
}
export interface TestDef extends Stamped {
  name: string
  note: string
  flows: TestFlow[]
  slo: Slo
  lastRun: LastRun | null
}

// ---------- 运行 ----------

export type Verdict = 'passed' | 'failed' | 'invalid' | 'error' | 'aborted'
export type RunStatus = 'running' | 'finished'

export interface RunSummary {
  reqs: number | null
  rps: number | null
  p95: number | null
  errorRate: number | null
  checksRate: number | null
}

/** 列表项：不含 snapshot 和 record */
export interface RunListItem {
  runId: string
  testId: number | null
  testName: string
  profileId: number | null
  profileName: string
  envId: number | null
  envName: string
  /** 发起时被测环境的类型。旧的运行记录没有这个字段 */
  envType?: EnvType | null
  executorId?: number | null
  executorName?: string | null
  status: RunStatus
  verdict: Verdict | null
  startedAt: string
  endedAt: string | null
  exitCode: number | null
  note: string
  archived: boolean
  summary: RunSummary | null
  /** 已经请求停止、k6 还没退出 */
  stopRequested?: boolean
  /** 运行中：k6 日志里最新的一行进度，原样显示 */
  progress?: string | null
}

/** 详情 */
export interface Run extends RunListItem {
  snapshot: Plan | null
  record: RunRecord | null
  /** 已存在的产物文件名。dashboard.html 是可选的：运行很短或启动失败时不存在 */
  artifacts: string[]
}

export interface RunStartInput {
  testId: number
  profileId: number
  envId: number
  /** 可省略，默认用本机执行机 */
  executorId?: number
  /** 被测环境类型为 prod 时必须为 true，否则预检不通过 */
  confirmProd?: boolean
  note: string
}

export interface RunListQuery {
  testId?: number
  verdict?: Verdict
  status?: RunStatus
  archived?: boolean
  page: number
  pageSize: number
}
export interface RunListResult {
  items: RunListItem[]
  total: number
}

export interface RunPatch {
  note?: string
  archived?: boolean
}

export type ArtifactName =
  | 'plan.json'
  | 'run-record.json'
  | 'k6-summary.json'
  | 'dashboard.html'
  | 'k6.log'

// ---------- plan.json（契约 §4），作为运行的 snapshot ----------

export interface PlanStep {
  key: string
  name: string
  method: HttpMethod
  path: string
  headers: Record<string, string>
  body: string | null
  expectStatus: number
  expectBodyContains: string | null
  extracts: Extract[]
  thinkTimeMs: number
}
export interface PlanFlow {
  key: string
  name: string
  weight: number
  steps: PlanStep[]
}
export interface Plan {
  schemaVersion: number
  runId: string
  test: { id: number; name: string }
  env: { id: number; name: string; type?: EnvType; baseUrl: string; headers: Record<string, string> }
  profile: { id: number; name: string; type: ProfileType; model: LoadModel; config: ProfileConfig }
  flows: PlanFlow[]
  slo: Slo
}

// ---------- Run Record（契约 §5） ----------

export type ThresholdKind = 'slo' | 'validity'

export interface Threshold {
  metric: string
  expr: string
  kind: ThresholdKind
  ok: boolean
  label: string
}

/**
 * 时间类指标单位都是毫秒。
 * 没有样本时是 null 而不是 0：整个运行没有发出任何请求时，时间类字段和 errorRate、checksRate 为 null。
 */
export interface OverallMetrics {
  reqs: number
  rps: number
  iterations: number
  droppedIterations: number
  vusMax: number
  avg: number | null
  p50: number | null
  p90: number | null
  p95: number | null
  p99: number | null
  max: number | null
  errorRate: number | null
  checksRate: number | null
  dataReceived: number
  dataSent: number
}

/** 某个步骤一次请求都没发出时，count 为 0，其余数值字段为 null。 */
export interface StepMetrics {
  flowKey: string
  flowName: string
  stepKey: string
  stepName: string
  /** 这一步发出的 HTTP 请求数；被自动跟随的重定向每一跳各算一次 */
  count: number
  avg: number | null
  p50: number | null
  p95: number | null
  p99: number | null
  max: number | null
  errorRate: number | null
}

export interface RunRecord {
  schemaVersion: number
  runId: string
  /** k6 没有产出记录时，后端仍会生成一份 record，此时为 null */
  k6Verdict: 'passed' | 'failed' | 'invalid' | null
  thresholds: Threshold[]
  /** k6 没有产出记录时为 null */
  metrics: {
    overall: OverallMetrics
    steps: StepMetrics[]
  } | null
  testDurationMs: number | null
  // 以下字段由后端在 k6 退出后补全
  verdict?: Verdict
  /** 一句中文原因，说明为什么是这个判定 */
  verdictReason?: string
  exitCode?: number | null
  window?: { start: string; end: string }
  fingerprint?: { k6Version: string; pythonVersion: string; gitSha: string; host: string }
  test?: { id: number; name: string }
  profile?: { id: number; name: string; model: LoadModel }
  env?: { id: number; name: string; type?: EnvType; baseUrl: string }
  /** 运行期间对执行机的采样。只作为信息展示，不参与判定。旧的运行记录没有 */
  executor?: RecordExecutor | null
}

export interface RecordExecutor {
  id: number
  name: string
  host: string | null
  cpuCores: number | null
  memTotalMb: number | null
  /** 没有采到样本时三个百分比为 null、samples 为 0 */
  cpuAvgPct: number | null
  cpuMaxPct: number | null
  memMaxPct: number | null
  samples: number
}

// ---------- 其他（契约 §3.3） ----------

export interface SystemInfo {
  k6Version: string
  pythonVersion: string
  /** 前端不使用：浏览器连着 k6 实时仪表盘时 k6 跑完不会退出，所以不嵌入也不链接它 */
  dashboardPort: number
  runningRunId: string | null
}

export interface Overview {
  counts: {
    /** 契约 §3.4 的示例里没有这一项；没有时前端自己数 */
    executors?: number
    environments: number
    apis: number
    flows: number
    profiles: number
    tests: number
    runs: number
  }
  verdicts: Record<Verdict, number>
  recentRuns: RunListItem[]
  runningRunId: string | null
}

// ---------- 调试（契约 §3.5、§5.1） ----------

export type DebugStepStatus = 'passed' | 'failed' | 'skipped' | 'error'

/** 这一步实际发出的请求（变量已替换、请求头已和被测环境合并） */
export interface DebugRequestInfo {
  method: string
  url: string
  headers: Record<string, string>
  body: string | null
}

export interface DebugResponseInfo {
  /** 没有收到响应（连接失败等）时为 0 */
  status: number
  statusText: string | null
  /** 有重定向时是最后一跳的地址 */
  finalUrl: string | null
  headers: Record<string, string>
  contentType: string | null
  /** 截断前的字符数 */
  bodyLength: number
  /** 不像文本（bodyOmitted）时为 null */
  body: string | null
  bodyTruncated: boolean
  bodyOmitted: boolean
}

/** 单位毫秒，对应 k6 的 res.timings */
export interface DebugTimings {
  durationMs: number | null
  blockedMs: number | null
  lookingUpMs: number | null
  connectingMs: number | null
  tlsMs: number | null
  sendingMs: number | null
  waitingMs: number | null
  receivingMs: number | null
}

export interface DebugCheck {
  name: string
  ok: boolean
}

export interface DebugExtracted {
  var: string
  from: ExtractFrom
  expr: string
  ok: boolean
  value: string | null
}

export interface DebugStep {
  key: string
  name: string
  status: DebugStepStatus
  /** skipped / error 时为 null */
  request: DebugRequestInfo | null
  response: DebugResponseInfo | null
  timings: DebugTimings | null
  /** 网络错误、脚本异常、或 skipped 的原因 */
  error: string | null
  checks: DebugCheck[]
  extracted: DebugExtracted[]
  /** 这一步之后的全部变量 */
  vars: Record<string, string>
}

/** api 和 flowId 恰好给一个 */
export interface DebugInput {
  envId: number
  /** 被测环境类型为 prod 时必须为 true */
  confirmProd?: boolean
  /** 初始变量 */
  vars?: Record<string, string>
  /** 一份接口定义，不要求已保存 */
  api?: ApiDefInput
  flowId?: number
}

export interface DebugSource {
  kind: 'api' | 'flow'
  id?: number
  name: string
}

export interface DebugResult {
  debugId: string
  /** 所有步骤都 passed */
  ok: boolean
  env: { id: number; name: string; type: EnvType; baseUrl: string }
  source: DebugSource
  /** 后端从启动 k6 到它退出的墙钟时间，不是响应时间 */
  durationMs: number
  exitCode: number | null
  steps: DebugStep[]
  vars: Record<string, string>
}
