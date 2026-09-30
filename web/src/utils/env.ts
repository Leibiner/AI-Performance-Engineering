import type { EnvType } from '../api'

export interface EnvTypeMeta {
  label: string
  tag: 'info' | 'primary' | 'warning' | 'danger'
  /** 生产用实心的红色标签，其余用描边 */
  effect: 'plain' | 'dark'
}

export const ENV_TYPES: Record<EnvType, EnvTypeMeta> = {
  dev: { label: '开发', tag: 'info', effect: 'plain' },
  test: { label: '测试', tag: 'primary', effect: 'plain' },
  staging: { label: '预发', tag: 'warning', effect: 'plain' },
  prod: { label: '生产', tag: 'danger', effect: 'dark' },
}

export const ENV_TYPE_OPTIONS = (Object.keys(ENV_TYPES) as EnvType[]).map((value) => ({
  value,
  label: `${ENV_TYPES[value].label}（${value}）`,
}))

export function envTypeLabel(type: EnvType | null | undefined): string {
  return type ? (ENV_TYPES[type]?.label ?? type) : ''
}

/** 安全上限：null 表示不限制 */
export function formatLimit(value: number | null | undefined, unit = ''): string {
  if (value === null || value === undefined) return '不限制'
  return unit ? `${value} ${unit}` : String(value)
}
