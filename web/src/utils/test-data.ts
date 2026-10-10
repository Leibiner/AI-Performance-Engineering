import type { DatasetOnExhausted, DatasetPick, DatasetSource, StepPhase } from '../api'
import { formatBytes } from './format'

export const PICK_OPTIONS: { value: DatasetPick; label: string }[] = [
  { value: 'sequential', label: '按顺序' },
  { value: 'random', label: '随机' },
  { value: 'perVu', label: '每个 VU 固定一行' },
]
export const PICK_LABELS: Record<DatasetPick, string> = Object.fromEntries(
  PICK_OPTIONS.map((o) => [o.value, o.label]),
) as Record<DatasetPick, string>

export const EXHAUSTED_OPTIONS: { value: DatasetOnExhausted; label: string }[] = [
  { value: 'recycle', label: '循环使用' },
  { value: 'stop', label: '停止测试' },
]
export const EXHAUSTED_LABELS: Record<DatasetOnExhausted, string> = Object.fromEntries(
  EXHAUSTED_OPTIONS.map((o) => [o.value, o.label]),
) as Record<DatasetOnExhausted, string>

export const PHASE_LABELS: Record<StepPhase, string> = { init: '初始化', main: '每次迭代' }
export const INIT_SEGMENT_TITLE = '初始化（每个 VU 一次）'
export const MAIN_SEGMENT_TITLE = '每次迭代'

const ENCODING_LABELS: Record<string, string> = { 'utf-8': 'UTF-8', 'utf-8-sig': 'UTF-8（BOM）', gb18030: 'GB18030' }
const DELIMITER_LABELS: Record<string, string> = { ',': '逗号', '\t': 'Tab', ';': '分号' }

export function encodingLabel(encoding: string | null | undefined): string {
  return encoding ? (ENCODING_LABELS[encoding] ?? encoding) : '—'
}
export function delimiterLabel(delimiter: string | null | undefined): string {
  return delimiter ? (DELIMITER_LABELS[delimiter] ?? JSON.stringify(delimiter)) : '—'
}
export function describeSource(source: DatasetSource | null | undefined): string {
  if (!source) return ''
  return `${encodingLabel(source.encoding)} · ${delimiterLabel(source.delimiter)}分隔`
}

/** 数据集和文件的上限都是 10 MiB（契约 §3.6、§3.7） */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

export function oversizeMessage(file: File): string | null {
  return file.size > MAX_UPLOAD_BYTES ? `「${file.name}」${formatBytes(file.size)}，超过 10 MiB` : null
}

/** 文件的原始字节 → base64（不带 data: 前缀） */
export function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const url = String(reader.result ?? '')
      resolve(url.slice(url.indexOf(',') + 1))
    }
    reader.onerror = () => reject(reader.error ?? new Error(`读取「${file.name}」失败`))
    reader.readAsDataURL(file)
  })
}
