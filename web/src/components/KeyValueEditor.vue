<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import type { KvRow } from '../utils/kv'
import VarInput from './VarInput.vue'

// 键值对编辑器：v-model 绑定行数组，保存时用 utils/kv 的 fromRows 转成对象。
const rows = defineModel<KvRow[]>({ required: true })

withDefaults(
  defineProps<{
    keyPlaceholder?: string
    valuePlaceholder?: string
    addText?: string
    /** 给出时值输入框高亮 {{变量}}，并按这些变量判断是否已定义 */
    vars?: Record<string, string>
    producers?: Record<string, string[]>
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
      <div v-if="vars" class="grow">
        <VarInput
          :model-value="row.value"
          :vars="vars"
          :producers="producers"
          :placeholder="valuePlaceholder"
          @update:model-value="update(index, 'value', $event)"
        />
      </div>
      <el-input
        v-else
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
