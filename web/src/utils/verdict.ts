import type { Verdict } from '../api'

export interface VerdictMeta {
  label: string
  /** 主色：横幅背景、标签文字 */
  color: string
  /** 浅色底：标签背景 */
  soft: string
  description: string
}

// 五种判定必须一眼能区分：绿 / 红 / 橙 / 紫 / 灰。
export const VERDICTS: Record<Verdict, VerdictMeta> = {
  passed: {
    label: '通过',
    color: '#1f8a3b',
    soft: '#e6f4ea',
    description: '测试有效，且所有验收标准都达标。',
  },
  failed: {
    label: '未达标',
    color: '#d03b3b',
    soft: '#fbe9e9',
    description: '测试有效，但被测系统没有达到验收标准。',
  },
  invalid: {
    label: '测试无效',
    color: '#d9730d',
    soft: '#fdf0e1',
    description: '有效性检查未通过，本次测试本身不可信，不能据此判断系统是否达标。',
  },
  error: {
    label: '执行出错',
    color: '#6b3fa0',
    soft: '#f0e9f7',
    description: 'k6 没有正常完成，或没有产出可用的运行记录。请查看 k6.log。',
  },
  aborted: {
    label: '已中止',
    color: '#6b7280',
    soft: '#eceef1',
    description: '运行被手动停止或被 k6 中止，结果不完整。',
  },
}

export const VERDICT_ORDER: Verdict[] = ['passed', 'failed', 'invalid', 'error', 'aborted']

export const VERDICT_OPTIONS = VERDICT_ORDER.map((value) => ({ value, label: VERDICTS[value].label }))
