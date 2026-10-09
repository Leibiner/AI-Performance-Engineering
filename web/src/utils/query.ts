// 接口路径里的 query 字符串 ↔ 键值对行。路径是唯一的事实来源，"参数"标签页只是它的另一种编辑方式。
// 不做 URL 编解码：路径里可以写 {{变量}}，编码由 k6 在发送时处理。
import type { KvRow } from './kv'

export interface SplitPath {
  /** ? 之前的部分 */
  pathname: string
  rows: KvRow[]
}

export function splitPath(path: string): SplitPath {
  const i = path.indexOf('?')
  if (i < 0) return { pathname: path, rows: [] }
  const query = path.slice(i + 1)
  const rows = query === ''
    ? []
    : query.split('&').map((part) => {
        const j = part.indexOf('=')
        return j < 0 ? { key: part, value: '' } : { key: part.slice(0, j), value: part.slice(j + 1) }
      })
  return { pathname: path.slice(0, i), rows }
}

/** 键为空的行不进路径（还在输入中）。 */
export function joinPath(pathname: string, rows: KvRow[]): string {
  const parts = rows.filter((r) => r.key.trim() !== '').map((r) => `${r.key.trim()}=${r.value}`)
  return parts.length ? `${pathname}?${parts.join('&')}` : pathname
}
