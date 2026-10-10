import { computed, ref, watch } from 'vue'
import { datasetsApi, type DatasetDetail } from '../api'
import { useDatasetList } from './useDatasetList'
import { useDebugContext } from './useDebugContext'

/** 环境 id → 调试单个接口时用的数据行 */
const STORAGE_KEY = 'perf-console.debugRows'

export interface RowChoice {
  datasetId: number
  /** 从 0 开始 */
  row: number
}

function readStored(): Record<string, RowChoice> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const data: unknown = raw ? JSON.parse(raw) : {}
    if (!data || typeof data !== 'object') return {}
    const out: Record<string, RowChoice> = {}
    for (const [env, value] of Object.entries(data as Record<string, unknown>)) {
      const c = value as Partial<RowChoice> | null
      if (c && Number.isInteger(c.datasetId) && Number.isInteger(c.row) && (c.row as number) >= 0) {
        out[env] = { datasetId: c.datasetId as number, row: c.row as number }
      }
    }
    return out
  } catch {
    return {}
  }
}

const byEnv = ref<Record<string, RowChoice>>(readStored())
watch(
  byEnv,
  (value) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
    } catch {
      // 写不了就只在本次会话里有效
    }
  },
  { deep: true },
)

/** 选中的数据集的详情（前 100 行），用来显示和高亮这一行的值 */
const details = ref<Record<number, DatasetDetail>>({})

export function useDebugRows() {
  const { envId } = useDebugContext()
  const { datasets, loaded, refresh } = useDatasetList()

  const choice = computed<RowChoice | null>(() =>
    envId.value === undefined ? null : (byEnv.value[String(envId.value)] ?? null),
  )
  function setChoice(next: RowChoice | null): void {
    if (envId.value === undefined) return
    const all = { ...byEnv.value }
    if (next) all[String(envId.value)] = next
    else delete all[String(envId.value)]
    byEnv.value = all
  }

  /** 选过但已被删除的数据集当作没选 */
  const dataset = computed(() => {
    const c = choice.value
    return c ? (datasets.value.find((d) => d.id === c.datasetId) ?? null) : null
  })
  const problem = computed<string | null>(() => {
    const d = dataset.value
    const c = choice.value
    if (!d || !c || c.row < d.rowCount) return null
    return `数据集「${d.name}」只有 ${d.rowCount} 行`
  })

  /** 列 → 这一行的值；行不在前 100 行里或详情还没取到时为 null */
  const rowValues = computed<Record<string, string> | null>(() => {
    const d = dataset.value
    const c = choice.value
    const detail = d ? details.value[d.id] : undefined
    if (!d || !c || !detail || detail.updatedAt !== d.updatedAt) return null
    const row = detail.previewRows[c.row]
    return row ? Object.fromEntries(detail.columns.map((col, i) => [col, row[i] ?? ''])) : null
  })
  /** 值未知时给变量高亮用的来源说明 */
  const hints = computed<Record<string, string>>(() => {
    const d = dataset.value
    const c = choice.value
    if (!d || !c || rowValues.value) return {}
    return Object.fromEntries(d.columns.map((col) => [col, `数据集「${d.name}」第 ${c.row + 1} 行`]))
  })
  const rowsParam = computed<Record<string, number> | undefined>(() => {
    const d = dataset.value
    const c = choice.value
    return d && c && !problem.value ? { [String(d.id)]: c.row } : undefined
  })

  async function ensureDetail(): Promise<void> {
    const d = dataset.value
    const c = choice.value
    if (!d || !c || c.row >= 100) return
    const cached = details.value[d.id]
    if (cached && cached.updatedAt === d.updatedAt) return
    try {
      const detail = await datasetsApi.get(d.id)
      details.value = { ...details.value, [d.id]: detail }
    } catch {
      // 只用于显示这一行的值，取不到就只标出列名
    }
  }

  return { choice, setChoice, datasets, loaded, refresh, dataset, problem, rowValues, hints, rowsParam, ensureDetail }
}
