// 键值对编辑器用的行结构，与接口里的 Record<string, string> 互转。

export interface KvRow {
  key: string
  value: string
}

export function toRows(record: Record<string, string> | null | undefined): KvRow[] {
  return Object.entries(record ?? {}).map(([key, value]) => ({ key, value: String(value) }))
}

/** 丢弃键为空的行；键去掉首尾空格。 */
export function fromRows(rows: KvRow[]): Record<string, string> {
  const record: Record<string, string> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (key) record[key] = row.value
  }
  return record
}
