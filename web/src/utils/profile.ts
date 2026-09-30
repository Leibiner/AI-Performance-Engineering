import type {
  ConstantRateConfig,
  ConstantVusConfig,
  LoadModel,
  ProfileConfig,
  ProfileType,
  RampingRateConfig,
  SharedIterationsConfig,
} from '../api'

/** 契约 §3.1 的四种 config 形态 */
export type ProfileShape = 'iterations' | 'vus' | 'rate' | 'ramping'

export interface ShapeMeta {
  model: LoadModel
  label: string
  executor: string
  description: string
}

export const SHAPES: Record<ProfileShape, ShapeMeta> = {
  iterations: {
    model: 'closed',
    label: '固定迭代数',
    executor: 'shared-iterations',
    description: '若干并发用户共同完成指定的迭代次数，做完即结束。适合冒烟。',
  },
  vus: {
    model: 'closed',
    label: '固定并发',
    executor: 'constant-vus',
    description: '固定数量的并发用户在指定时长内循环执行。',
  },
  rate: {
    model: 'open',
    label: '固定到达率',
    executor: 'constant-arrival-rate',
    description: '每秒发起固定次数的迭代，持续指定时长。',
  },
  ramping: {
    model: 'open',
    label: '阶梯到达率',
    executor: 'ramping-arrival-rate',
    description: '从起始到达率开始，按阶段逐步变化到各自的目标值。',
  },
}

export const SHAPES_BY_MODEL: Record<LoadModel, ProfileShape[]> = {
  closed: ['iterations', 'vus'],
  open: ['rate', 'ramping'],
}

export const MODEL_LABELS: Record<LoadModel, string> = {
  closed: 'closed（固定并发）',
  open: 'open（固定到达率）',
}

export const PROFILE_TYPE_LABELS: Record<ProfileType, string> = {
  smoke: '冒烟',
  average: '平均负载',
  stress: '压力',
  spike: '尖峰',
  soak: '浸泡',
  breakpoint: '断点',
}

export const PROFILE_TYPE_OPTIONS = (Object.keys(PROFILE_TYPE_LABELS) as ProfileType[]).map((value) => ({
  value,
  label: `${PROFILE_TYPE_LABELS[value]}（${value}）`,
}))

export function shapeOf(model: LoadModel, config: ProfileConfig): ProfileShape {
  if (model === 'closed') return 'iterations' in config ? 'iterations' : 'vus'
  return 'stages' in config ? 'ramping' : 'rate'
}

/** 负载配置对环境上限的需求，用于在发起运行前和环境上限对照。 */
export interface ProfileDemand {
  /** 并发：vus 或 preAllocatedVus */
  vus: number
  /** 最大到达率（每秒迭代数）；closed 模型没有 */
  rate: number | null
  /** 总时长（秒） */
  durationSec: number
}

export function demandOf(model: LoadModel, config: ProfileConfig): ProfileDemand {
  switch (shapeOf(model, config)) {
    case 'iterations': {
      const c = config as SharedIterationsConfig
      return { vus: c.vus, rate: null, durationSec: c.maxDurationSec }
    }
    case 'vus': {
      const c = config as ConstantVusConfig
      return { vus: c.vus, rate: null, durationSec: c.durationSec }
    }
    case 'rate': {
      const c = config as ConstantRateConfig
      return { vus: c.preAllocatedVus, rate: c.rate, durationSec: c.durationSec }
    }
    case 'ramping': {
      const c = config as RampingRateConfig
      const stages = c.stages ?? []
      return {
        vus: c.preAllocatedVus,
        rate: Math.max(c.startRate, ...stages.map((s) => s.target)),
        durationSec: stages.reduce((sum, s) => sum + s.durationSec, 0),
      }
    }
  }
}

/** 一句话描述负载配置的内容，用于表格和选择框。 */
export function describeConfig(model: LoadModel, config: ProfileConfig): string {
  switch (shapeOf(model, config)) {
    case 'iterations': {
      const c = config as SharedIterationsConfig
      return `${c.vus} 并发，共 ${c.iterations} 次迭代，最长 ${c.maxDurationSec} 秒`
    }
    case 'vus': {
      const c = config as ConstantVusConfig
      return `${c.vus} 并发，持续 ${c.durationSec} 秒`
    }
    case 'rate': {
      const c = config as ConstantRateConfig
      return `每秒 ${c.rate} 次，持续 ${c.durationSec} 秒，预分配 ${c.preAllocatedVus} 并发`
    }
    case 'ramping': {
      const c = config as RampingRateConfig
      const path = [c.startRate, ...(c.stages ?? []).map((s) => s.target)].join(' → ')
      const total = (c.stages ?? []).reduce((sum, s) => sum + s.durationSec, 0)
      return `每秒 ${path} 次，共 ${total} 秒，预分配 ${c.preAllocatedVus} 并发`
    }
  }
}
