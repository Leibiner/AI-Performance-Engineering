<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowDown, Folder as FolderIcon, FolderOpened, MoreFilled, Plus, Search } from '@element-plus/icons-vue'
import type { ElTree } from 'element-plus'
import type { ApiDef, Folder } from '../../api'
import { buildFolderTree, type FolderNode } from '../../utils/folders'
import { METHOD_COLOR } from '../../utils/method'

interface TreeItem {
  key: string
  kind: 'folder' | 'api' | 'draft'
  label: string
  folder?: Folder
  api?: ApiDef
  total?: number
  children?: TreeItem[]
}

const props = defineProps<{
  items: ApiDef[]
  folders: Folder[]
  selectedId: number | null
  /** undefined = 没有在新建；null = 新建在根目录；数字 = 新建在该文件夹下 */
  draftFolderId: number | null | undefined
  loading: boolean
}>()
const emit = defineEmits<{
  select: [api: ApiDef]
  create: [folderId: number | null]
  import: [folderId: number | null]
  'import-doc': []
  'create-folder': [parentId: number | null]
  'rename-folder': [folder: Folder]
  'delete-folder': [folder: Folder]
}>()

const keyword = ref('')
const treeRef = ref<InstanceType<typeof ElTree>>()

function apiItem(api: ApiDef): TreeItem {
  return { key: `a-${api.id}`, kind: 'api', label: `${api.name} ${api.method} ${api.path}`, api }
}
function draftItem(): TreeItem {
  return { key: 'draft', kind: 'draft', label: '新接口（未保存）' }
}
function folderItem(node: FolderNode): TreeItem {
  const children: TreeItem[] = [...node.children.map(folderItem), ...node.apis.map(apiItem)]
  if (props.draftFolderId === node.folder.id) children.unshift(draftItem())
  return { key: `f-${node.folder.id}`, kind: 'folder', label: node.folder.name, folder: node.folder, total: node.total, children }
}

const data = computed<TreeItem[]>(() => {
  const tree = buildFolderTree(props.folders, props.items)
  const out: TreeItem[] = tree.roots.map(folderItem)
  if (props.draftFolderId === null) out.push(draftItem())
  out.push(...tree.rootApis.map(apiItem))
  return out
})
const isEmpty = computed(() => props.items.length === 0 && props.folders.length === 0 && props.draftFolderId === undefined)

// 展开的文件夹记在本地，回到接口页时树还是离开时的样子
const EXPANDED_KEY = 'perf-console.apis.expanded'
function readExpanded(): string[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(EXPANDED_KEY) ?? '[]')
    return Array.isArray(saved) ? saved.filter((k): k is string => typeof k === 'string' && k.startsWith('f-')) : []
  } catch {
    return []
  }
}
const expanded = ref<string[]>(readExpanded())
watch(expanded, (keys) => {
  try {
    localStorage.setItem(EXPANDED_KEY, JSON.stringify(keys))
  } catch {
    // 存不了只是下次要重新展开
  }
})
function onExpand(item: TreeItem): void {
  if (!expanded.value.includes(item.key)) expanded.value = [...expanded.value, item.key]
}
function onCollapse(item: TreeItem): void {
  expanded.value = expanded.value.filter((k) => k !== item.key)
}
/** 某个文件夹的祖先链（含自己）的 key，用来把选中的接口所在的文件夹展开 */
function chainKeys(folderId: number | null | undefined): string[] {
  const map = new Map(props.folders.map((f) => [f.id, f]))
  const keys: string[] = []
  const seen = new Set<number>()
  let cursor = folderId ?? null
  while (cursor !== null && !seen.has(cursor)) {
    seen.add(cursor)
    const f = map.get(cursor)
    if (!f) break
    keys.push(`f-${f.id}`)
    cursor = f.parentId
  }
  return keys
}
function reveal(folderId: number | null | undefined): void {
  const keys = chainKeys(folderId).filter((k) => !expanded.value.includes(k))
  if (keys.length) expanded.value = [...expanded.value, ...keys]
}

const activeKey = ref<string | null>(null)
function applyCurrent(): void {
  void nextTick(() => {
    treeRef.value?.setCurrentKey(activeKey.value ?? undefined)
    // 回到上次的接口时它可能在长列表的下面
    const el = treeRef.value?.$el as HTMLElement | undefined
    el?.querySelector('.el-tree-node.is-current > .el-tree-node__content')?.scrollIntoView({ block: 'nearest' })
  })
}
watch(
  () => [props.selectedId, props.draftFolderId] as const,
  ([id, draft]) => {
    if (draft !== undefined) {
      activeKey.value = 'draft'
      reveal(draft)
    } else if (id !== null) {
      activeKey.value = `a-${id}`
      reveal(props.items.find((a) => a.id === id)?.folderId)
    }
    applyCurrent()
  },
  { immediate: true },
)
watch(data, applyCurrent)

function onNodeClick(item: TreeItem): void {
  if (item.kind === 'api' && item.api) {
    activeKey.value = item.key
    emit('select', item.api)
  }
  applyCurrent()
}
function onFolderCommand(command: string, folder: Folder): void {
  if (command === 'api') emit('create', folder.id)
  else if (command === 'subfolder') emit('create-folder', folder.id)
  else if (command === 'rename') emit('rename-folder', folder)
  else if (command === 'delete') emit('delete-folder', folder)
}
function onNewCommand(command: string): void {
  if (command === 'api') emit('create', null)
  else if (command === 'import') emit('import', null)
  else if (command === 'import-doc') emit('import-doc')
  else if (command === 'folder') emit('create-folder', null)
}

watch(keyword, (value) => treeRef.value?.filter(value.trim().toLowerCase()))
// el-tree 的类型里节点数据是 Record<string, any>，这里按字段取
function filterNode(value: string, item: Record<string, unknown>): boolean {
  const label = typeof item.label === 'string' ? item.label : ''
  return !value || label.toLowerCase().includes(value)
}
</script>

<template>
  <aside class="api-list">
    <div class="api-list-tools">
      <el-input v-model="keyword" :prefix-icon="Search" placeholder="搜索" clearable />
      <el-dropdown trigger="click" @command="onNewCommand">
        <el-button type="primary" :icon="Plus">
          新建<el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu class="new-menu">
            <el-dropdown-item command="api">新建接口</el-dropdown-item>
            <el-dropdown-item command="import">从 cURL 导入接口</el-dropdown-item>
            <el-dropdown-item command="import-doc">从 OpenAPI / Postman 导入接口</el-dropdown-item>
            <el-dropdown-item divided command="folder">新建文件夹</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div v-loading="loading" class="api-list-body">
      <el-tree
        ref="treeRef"
        :data="data"
        node-key="key"
        highlight-current
        :default-expanded-keys="expanded"
        :filter-node-method="filterNode"
        :indent="14"
        class="api-tree"
        @node-click="onNodeClick"
        @node-expand="onExpand"
        @node-collapse="onCollapse"
      >
        <template #default="{ node, data: item }">
          <div class="tree-row" :class="`is-${item.kind}`">
            <template v-if="item.kind === 'folder'">
              <el-icon class="tree-folder-icon">
                <FolderOpened v-if="node.expanded" />
                <FolderIcon v-else />
              </el-icon>
              <span class="tree-name">{{ item.folder.name }}</span>
              <span class="tree-count">{{ item.total }}</span>
              <el-dropdown trigger="click" class="tree-more" @command="(cmd: string) => onFolderCommand(cmd, item.folder)">
                <span class="tree-more-btn" title="文件夹操作" @click.stop>
                  <el-icon><MoreFilled /></el-icon>
                </span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="api">新建接口</el-dropdown-item>
                    <el-dropdown-item command="subfolder">新建子文件夹</el-dropdown-item>
                    <el-dropdown-item divided command="rename">重命名</el-dropdown-item>
                    <el-dropdown-item command="delete">删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
            <template v-else-if="item.kind === 'api'">
              <span class="tree-method" :style="{ color: METHOD_COLOR[item.api.method as keyof typeof METHOD_COLOR] }">{{ item.api.method }}</span>
              <span class="tree-name" :title="`${item.api.method} ${item.api.path}`">{{ item.api.name }}</span>
            </template>
            <template v-else>
              <span class="tree-method tree-method--new">新</span>
              <span class="tree-name">新接口（未保存）</span>
            </template>
          </div>
        </template>
      </el-tree>
      <div v-if="isEmpty" class="api-list-empty">暂无接口</div>
    </div>
  </aside>
</template>

<style scoped>
.api-list {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.api-list-tools {
  display: flex;
  gap: 6px;
  padding: 12px;
  border-bottom: 1px solid var(--hairline);
}
.api-list-tools .el-input {
  flex: 1;
  min-width: 0;
}
.api-list-body {
  flex: 1;
  min-height: 0;
  padding: 6px;
  overflow: auto;
}
.api-tree {
  --el-tree-node-content-height: 32px;
  --el-tree-node-hover-bg-color: #f4f5f7;
  background: transparent;
}
.api-tree :deep(.el-tree-node__content) {
  border-radius: 6px;
}
.api-tree :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: rgba(64, 158, 255, 0.12);
}
.api-tree :deep(.el-tree-node__expand-icon.is-leaf) {
  width: 6px;
  padding: 0;
}
.tree-row {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: 8px;
  padding-right: 4px;
}
.tree-folder-icon {
  flex-shrink: 0;
  color: #d9a441;
  font-size: 16px;
}
.tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
}
.is-folder .tree-name {
  font-weight: 600;
}
.tree-count {
  flex-shrink: 0;
  color: var(--ink-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.tree-more {
  flex-shrink: 0;
}
.tree-more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  color: var(--ink-muted);
  opacity: 0;
  transition: opacity 0.15s;
}
.tree-row:hover .tree-more-btn,
.el-tree-node.is-current > .el-tree-node__content .tree-more-btn {
  opacity: 1;
}
.tree-more-btn:hover {
  background: #e8ebf0;
  color: var(--el-text-color-primary);
}
.tree-method {
  flex-shrink: 0;
  width: 46px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.3px;
}
.tree-method--new {
  color: var(--el-color-primary);
}
.api-list-empty {
  padding: 28px 12px;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.6;
  text-align: center;
}
</style>
