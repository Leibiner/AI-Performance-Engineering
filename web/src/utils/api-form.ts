// 接口编辑器的表单模型，与契约的 ApiDefInput 互转。表单里用空字符串表示"没填"，保存时转成 null。
import type { ApiDefInput, Extract, HttpMethod } from '../api'
import { fromRows, toRows, type KvRow } from './kv'

export interface ApiForm {
  folderId: number | null
  name: string
  method: HttpMethod
  path: string
  headers: KvRow[]
  body: string
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
    body: '',
    expectStatus: 200,
    expectBodyContains: '',
    extracts: [],
    note: '',
  }
}

export function fromApi(api: ApiDefInput): ApiForm {
  return {
    folderId: api.folderId ?? null,
    name: api.name,
    method: api.method,
    path: api.path,
    headers: toRows(api.headers),
    body: api.body ?? '',
    expectStatus: api.expectStatus,
    expectBodyContains: api.expectBodyContains ?? '',
    extracts: (api.extracts ?? []).map((e) => ({ ...e })),
    note: api.note ?? '',
  }
}

export function toInput(form: ApiForm): ApiDefInput {
  return {
    folderId: form.folderId,
    name: form.name.trim(),
    method: form.method,
    path: form.path.trim(),
    headers: fromRows(form.headers),
    body: form.body === '' ? null : form.body,
    expectStatus: form.expectStatus,
    expectBodyContains: form.expectBodyContains === '' ? null : form.expectBodyContains,
    // 变量名和表达式都空的行是还没填完的，丢弃
    extracts: form.extracts
      .filter((e) => e.var.trim() !== '' || e.expr.trim() !== '')
      .map((e) => ({ var: e.var.trim(), from: e.from, expr: e.expr.trim() })),
    note: form.note,
  }
}

/** 用于判断"有没有改动"的快照 */
export function snapshot(form: ApiForm): string {
  return JSON.stringify(toInput(form))
}
