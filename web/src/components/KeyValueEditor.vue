<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import type { KvRow } from '../utils/kv'

// 键值对编辑器：v-model 绑定行数组，保存时用 utils/kv 的 fromRows 转成对象。
const rows = defineModel<KvRow[]>({ required: true })

withDefaults(
  defineProps<{
    keyPlaceholder?: string
    valuePlaceholder?: string
    addText?: string
  }>(),
  { keyPlaceholder: '名称', valuePlaceholder: '值', addText: '添加一行' },
)

function update(index: number, field: keyof KvRow, value: string): void {
  rows.value = rows.value.map((row, i) => (i === index ? { ...row, [field]: value } : row))
}
function add(): void {
  rows.value = [...rows.value, { key: '', value: '' }]
}
function remove(index: number): void {
  rows.value = rows.value.filter((_, i) => i !== index)
}
</script>

<template>
  <div class="row-list">
    <div v-for="(row, index) in rows" :key="index" class="row-item">
      <el-input
        :model-value="row.key"
        :placeholder="keyPlaceholder"
        style="width: 38%"
        @update:model-value="update(index, 'key', $event)"
      />
      <el-input
        class="grow"
        :model-value="row.value"
        :placeholder="valuePlaceholder"
        @update:model-value="update(index, 'value', $event)"
      />
      <el-button :icon="Delete" circle text title="删除这一行" @click="remove(index)" />
    </div>
    <el-button :icon="Plus" size="small" @click="add">{{ addText }}</el-button>
  </div>
</template>
