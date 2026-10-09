<script setup lang="ts">
import { computed, ref } from 'vue'
import { Plus, Search, Upload } from '@element-plus/icons-vue'
import type { ApiDef } from '../../api'
import { METHOD_COLOR } from '../../utils/method'

// 接口页左栏：搜索 + 列表。选中项由父组件决定。
const props = defineProps<{ items: ApiDef[]; selectedId: number | null; draftNew: boolean; loading: boolean }>()
const emit = defineEmits<{ select: [api: ApiDef]; create: []; import: [] }>()

const keyword = ref('')
const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return props.items
  return props.items.filter(
    (a) => a.name.toLowerCase().includes(k) || a.path.toLowerCase().includes(k) || a.method.toLowerCase().includes(k),
  )
})
</script>

<template>
  <aside class="api-list">
    <div class="api-list-tools">
      <el-input v-model="keyword" :prefix-icon="Search" placeholder="搜索名称或路径" clearable />
      <el-button type="primary" :icon="Plus" title="新建接口" @click="emit('create')">新建</el-button>
      <el-button :icon="Upload" title="粘贴 cURL 命令，生成接口" @click="emit('import')">cURL</el-button>
    </div>
    <div v-loading="loading" class="api-list-body">
      <div v-if="draftNew" class="api-item is-active">
        <span class="api-item-method api-item-method--new">新</span>
        <span class="api-item-text">
          <span class="api-item-name">新接口（未保存）</span>
        </span>
      </div>
      <button
        v-for="api in filtered"
        :key="api.id"
        type="button"
        class="api-item"
        :class="{ 'is-active': api.id === selectedId }"
        @click="emit('select', api)"
      >
        <span class="api-item-method" :style="{ color: METHOD_COLOR[api.method] }">{{ api.method }}</span>
        <span class="api-item-text">
          <span class="api-item-name">{{ api.name }}</span>
          <span class="api-item-path mono">{{ api.path }}</span>
        </span>
      </button>
      <div v-if="!filtered.length && !draftNew" class="api-list-empty">
        {{ items.length ? '没有匹配的接口' : '还没有接口。点“新建”，或从 cURL 导入一个。' }}
      </div>
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
.api-list-tools .el-button + .el-button {
  margin-left: 0;
}
.api-list-body {
  flex: 1;
  min-height: 0;
  padding: 6px;
  overflow-y: auto;
}
.api-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.api-item:hover {
  background: #f4f5f7;
}
.api-item:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}
.api-item.is-active {
  background: rgba(64, 158, 255, 0.12);
}
.api-item-method {
  flex-shrink: 0;
  width: 52px;
  padding-top: 2px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.3px;
}
.api-item-method--new {
  color: var(--el-color-primary);
}
.api-item-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.api-item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
}
.api-item-path {
  overflow: hidden;
  color: var(--ink-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.api-list-empty {
  padding: 28px 12px;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.6;
  text-align: center;
}
</style>
