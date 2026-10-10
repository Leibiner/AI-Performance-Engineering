// 接口编辑器的表单模型，与契约的 ApiDefInput 互转。表单里用空字符串表示"没填"，保存时转成 null。
import type { ApiDefInput, ApiFormItem, BodyType, Extract, FormItemType, HttpMethod } from '../api'
import { fromRows, toRows, type KvRow } from './kv'

/** none 存成 bodyType raw + body null */
export type BodyMode = 'none' | 'raw' | 'form' | 'multipart'

/** 同一行在文本和文件之间切换时两边的内容都留着，保存时按 type 取 */
export interface FormRow {
  name: string
  type: FormItemType
  value: string
  fileId: number | null
}

export interface ApiForm {
  folderId: number | null
  name: string
  method: HttpMethod
  path: string
  headers: KvRow[]
  bodyMode: BodyMode
  body: string
  form: FormRow[]
  expectStatus: number
  expectBodyContains: string
  extracts: Extract[]
  note: string
}

export function emptyForm(folderId: number | null = null): ApiForm {
  return {
    folderId,
    name: '',
    method: 'GET',
    path: '/',
    headers: [],
    bodyMode: 'none',
    body: '',
    form: [],
    expectStatus: 200,
    expectBodyContains: '',
    extracts: [],
    note: '',
  }
}

function modeOf(bodyType: BodyType | undefined, body: string | null): BodyMode {
  if (bodyType === 'form' || bodyType === 'multipart') return bodyType
  return body === null || body === '' ? 'none' : 'raw'
}

export function fromApi(api: ApiDefInput): ApiForm {
  return {
    folderId: api.folderId ?? null,
    name: api.name,
    method: api.method,
    path: api.path,
    headers: toRows(api.headers),
    bodyMode: modeOf(api.bodyType, api.body),
    body: api.body ?? '',
    form: (api.form ?? []).map((item) => ({
      name: item.name,
      type: item.type,
      value: item.value ?? '',
      fileId: item.fileId ?? null,
    })),
    expectStatus: api.expectStatus,
    expectBodyContains: api.expectBodyContains ?? '',
    extracts: (api.extracts ?? []).map((e) => ({ ...e })),
    note: api.note ?? '',
  }
}

export function isBlankRow(row: FormRow): boolean {
  return row.name.trim() === '' && row.value === '' && row.fileId === null
}

export function toFormItems(rows: FormRow[]): ApiFormItem[] {
  return rows
    .filter((r) => !isBlankRow(r))
    .map((r) =>
      r.type === 'file'
        ? { name: r.name, type: 'file', value: '', fileId: r.fileId }
        : { name: r.name, type: 'text', value: r.value, fileId: null },
    )
}

export function toInput(form: ApiForm): ApiDefInput {
  const bodyType: BodyType = form.bodyMode === 'form' || form.bodyMode === 'multipart' ? form.bodyMode : 'raw'
  return {
    folderId: form.folderId,
    name: form.name.trim(),
    method: form.method,
    path: form.path.trim(),
    headers: fromRows(form.headers),
    bodyType,
    body: form.bodyMode === 'none' || form.body === '' ? null : form.body,
    form: toFormItems(form.form),
    expectStatus: form.expectStatus,
    expectBodyContains: form.expectBodyContains === '' ? null : form.expectBodyContains,
    // 变量名和表达式都空的行是还没填完的，丢弃
    extracts: form.extracts
      .filter((e) => e.var.trim() !== '' || e.expr.trim() !== '')
      .map((e) => ({ var: e.var.trim(), from: e.from, expr: e.expr.trim() })),
    note: form.note,
  }
}

/** 保存或发送前前端能看出来的问题；后端仍会完整校验 */
export function formProblem(form: ApiForm): string | null {
  if (form.bodyMode !== 'form' && form.bodyMode !== 'multipart') return null
  for (const [i, row] of form.form.entries()) {
    if (isBlankRow(row)) continue
    const label = row.name.trim() ? `「${row.name.trim()}」` : `第 ${i + 1} 项`
    if (!row.name.trim()) return `表单${label}没有名称`
    if (row.type !== 'file') continue
    if (form.bodyMode === 'form') return `x-www-form-urlencoded 不能包含文件项${label}`
    if (row.fileId === null) return `form-data 的文件项${label}还没有选择文件`
  }
  return null
}

/** 用于判断"有没有改动"的快照 */
export function snapshot(form: ApiForm): string {
  return JSON.stringify(toInput(form))
}
