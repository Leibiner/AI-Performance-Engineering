// 接口文件夹树：把扁平的 folders + apis 组装成左栏的树，以及选择上级 / 所属文件夹用的选项树。
import type { ApiDef, Folder } from '../api'

export interface FolderNode {
  folder: Folder
  children: FolderNode[]
  apis: ApiDef[]
  /** 含子孙在内的接口数 */
  total: number
}

export interface FolderTree {
  roots: FolderNode[]
  /** 根目录下的接口（folderId 为 null，或指向的文件夹已不存在） */
  rootApis: ApiDef[]
}

const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name, 'zh-Hans-CN')

/** 组树。上级不存在或成环的文件夹当作顶层处理，不会丢。 */
export function buildFolderTree(folders: Folder[], apis: ApiDef[]): FolderTree {
  const nodes = new Map<number, FolderNode>()
  for (const f of folders) nodes.set(f.id, { folder: f, children: [], apis: [], total: 0 })
  for (const api of apis) {
    const node = api.folderId !== null && api.folderId !== undefined ? nodes.get(api.folderId) : undefined
    if (node) node.apis.push(api)
  }
  const rootApis = apis.filter((a) => a.folderId === null || a.folderId === undefined || !nodes.has(a.folderId))

  const roots: FolderNode[] = []
  const placed = new Set<number>()
  for (const node of nodes.values()) {
    const parent = node.folder.parentId !== null ? nodes.get(node.folder.parentId) : undefined
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }
  // 成环的（互为上级）谁都不在 roots 里：从 roots 走一遍，没走到的提到顶层
  const visit = (node: FolderNode): number => {
    placed.add(node.folder.id)
    node.children.sort((a, b) => byName(a.folder, b.folder))
    node.apis.sort(byName)
    node.total = node.apis.length + node.children.reduce((sum, c) => sum + visit(c), 0)
    return node.total
  }
  roots.forEach(visit)
  for (const node of nodes.values()) {
    if (!placed.has(node.folder.id)) {
      roots.push(node)
      visit(node)
    }
  }
  roots.sort((a, b) => byName(a.folder, b.folder))
  rootApis.sort(byName)
  return { roots, rootApis }
}

/** 文件夹的完整路径，如「订单系统 / 下单」 */
export function folderPath(folders: Folder[], id: number | null | undefined): string {
  if (id === null || id === undefined) return ''
  const map = new Map(folders.map((f) => [f.id, f]))
  const names: string[] = []
  const seen = new Set<number>()
  let cursor: number | null = id
  while (cursor !== null && !seen.has(cursor)) {
    seen.add(cursor)
    const f = map.get(cursor)
    if (!f) break
    names.unshift(f.name)
    cursor = f.parentId
  }
  return names.join(' / ')
}

export interface FolderOption {
  value: number
  label: string
  children?: FolderOption[]
  disabled?: boolean
}

/**
 * 树形选择器的数据。exclude 给出时，该文件夹和它的子孙不可选（移动文件夹时不能选自己和子孙）。
 */
export function folderOptions(roots: FolderNode[], exclude?: number | null): FolderOption[] {
  const walk = (nodes: FolderNode[], under: boolean): FolderOption[] =>
    nodes.map((n) => {
      const disabled = under || n.folder.id === exclude
      const children = walk(n.children, disabled)
      return { value: n.folder.id, label: n.folder.name, disabled, ...(children.length ? { children } : {}) }
    })
  return walk(roots, false)
}
