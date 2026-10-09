// 和引擎（perf/core/interp.js）相同的变量写法：{{ 名称 }}，名称两侧允许空格
const VAR_PATTERN = /\{\{\s*([^{}\s]+)\s*\}\}/g

export interface TextSegment {
  text: string
  /** 变量名；普通文本为 null */
  name: string | null
}

export function splitVars(text: string): TextSegment[] {
  const out: TextSegment[] = []
  let last = 0
  for (const m of text.matchAll(VAR_PATTERN)) {
    const start = m.index ?? 0
    if (start > last) out.push({ text: text.slice(last, start), name: null })
    out.push({ text: m[0], name: m[1] })
    last = start + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last), name: null })
  return out
}

export function varNames(text: string): string[] {
  return [...new Set([...text.matchAll(VAR_PATTERN)].map((m) => m[1]))]
}
