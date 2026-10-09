// 唯一的数据访问层。页面只调用这里的函数，不直接写 fetch。
import { apiUrl, request, requestText } from './http'
import type {
  ApiDef,
  ApiDefInput,
  ArtifactName,
  DebugInput,
  DebugResult,
  Environment,
  EnvironmentInput,
  Executor,
  ExecutorInput,
  Flow,
  FlowInput,
  Folder,
  FolderInput,
  Overview,
  Profile,
  ProfileInput,
  Run,
  RunListQuery,
  RunListResult,
  RunPatch,
  RunStartInput,
  SystemInfo,
  TestDef,
  TestInput,
} from './types'

export { ApiError } from './http'
export type * from './types'

/** 定义类资源统一的增删改查（契约 §3.1）。 */
export interface ResourceApi<T, TInput> {
  list(): Promise<T[]>
  get(id: number): Promise<T>
  create(input: TInput): Promise<T>
  update(id: number, input: TInput): Promise<T>
  remove(id: number): Promise<void>
}

function resource<T, TInput>(name: string): ResourceApi<T, TInput> {
  return {
    list: () => request<T[]>('GET', `/${name}`),
    get: (id) => request<T>('GET', `/${name}/${id}`),
    create: (input) => request<T>('POST', `/${name}`, { body: input }),
    update: (id, input) => request<T>('PUT', `/${name}/${id}`, { body: input }),
    remove: async (id) => {
      await request<unknown>('DELETE', `/${name}/${id}`)
    },
  }
}

/** 执行机没有新增和删除（契约 §3.3），只能查看和改名称、备注。 */
export const executorsApi = {
  list: () => request<Executor[]>('GET', '/executors'),
  get: (id: number) => request<Executor>('GET', `/executors/${id}`),
  update: (id: number, input: ExecutorInput) => request<Executor>('PUT', `/executors/${id}`, { body: input }),
}

export const environmentsApi = resource<Environment, EnvironmentInput>('environments')
export const foldersApi = resource<Folder, FolderInput>('folders')
export const apisApi = resource<ApiDef, ApiDefInput>('apis')
export const flowsApi = resource<Flow, FlowInput>('flows')
export const profilesApi = resource<Profile, ProfileInput>('profiles')
export const testsApi = resource<TestDef, TestInput>('tests')

function runPath(runId: string): string {
  return `/runs/${encodeURIComponent(runId)}`
}

export const runsApi = {
  /** 发起运行。预检不通过抛 422（details 逐条原因），已有运行在进行抛 409。 */
  start: (input: RunStartInput) => request<Run>('POST', '/runs', { body: input }),
  list: (query: RunListQuery) => request<RunListResult>('GET', '/runs', { query: { ...query } }),
  get: (runId: string) => request<Run>('GET', runPath(runId)),
  /** 停止运行，返回更新后的运行对象（stopRequested 为 true）。 */
  stop: (runId: string) => request<Run>('POST', `${runPath(runId)}/stop`),
  patch: (runId: string, patch: RunPatch) => request<Run>('PATCH', runPath(runId), { body: patch }),
  remove: async (runId: string) => {
    await request<unknown>('DELETE', runPath(runId))
  },
  /** 产物的访问地址，用于链接和 iframe。download 为 true 时浏览器会直接下载。 */
  artifactUrl: (runId: string, name: ArtifactName | string, download = false) =>
    apiUrl(`${runPath(runId)}/artifacts/${encodeURIComponent(name)}${download ? '?download=1' : ''}`),
  /** 以文本方式读取产物（如 k6.log）。 */
  artifactText: (runId: string, name: ArtifactName) =>
    requestText(`${runPath(runId)}/artifacts/${encodeURIComponent(name)}`),
}

/** 调试：用真实 k6 把一个接口或一个流程跑一次迭代（契约 §3.5）。同步返回，最长约 90 秒。 */
export const debugApi = {
  run: (input: DebugInput) => request<DebugResult>('POST', '/debug', { body: input }),
}

export const systemApi = {
  get: () => request<SystemInfo>('GET', '/system'),
}

export const overviewApi = {
  get: () => request<Overview>('GET', '/overview'),
}
