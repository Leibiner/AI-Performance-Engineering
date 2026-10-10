<script setup lang="ts">
import { ref } from 'vue'
import { datasetsApi, type Dataset } from '../../api'
import { useResourceList } from '../../composables/useResourceList'
import { formatCount, formatTime } from '../../utils/format'
import { describeSource } from '../../utils/test-data'
import DatasetDialog from './DatasetDialog.vue'

const { items, loading, load, remove } = useResourceList(datasetsApi, '数据集')

const MAX_TAGS = 6
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

function openCreate(): void {
  editingId.value = null
  dialogVisible.value = true
}
function openEdit(row: Dataset): void {
  editingId.value = row.id
  dialogVisible.value = true
}

defineExpose({ openCreate })
</script>

<template>
  <el-table v-loading="loading" :data="items" empty-text="暂无数据集">
    <el-table-column label="名称" min-width="160">
      <template #default="{ row }">
        <div>{{ (row as Dataset).name }}</div>
        <div class="muted ds-source">{{ describeSource((row as Dataset).source) }}</div>
      </template>
    </el-table-column>
    <el-table-column label="列" min-width="280">
      <template #default="{ row }">
        <div class="tag-line">
          <el-tag
            v-for="c in (row as Dataset).columns.slice(0, MAX_TAGS)"
            :key="c"
            size="small"
            type="info"
            effect="plain"
            class="mono"
            disable-transitions
          >
            {{ c }}
          </el-tag>
          <el-tooltip
            v-if="(row as Dataset).columns.length > MAX_TAGS"
            :content="(row as Dataset).columns.slice(MAX_TAGS).join('、')"
            placement="top"
          >
            <el-tag size="small" type="info" disable-transitions>+{{ (row as Dataset).columns.length - MAX_TAGS }}</el-tag>
          </el-tooltip>
        </div>
      </template>
    </el-table-column>
    <el-table-column label="行数" width="100" align="right">
      <template #default="{ row }">
        <span class="num">{{ formatCount((row as Dataset).rowCount) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="绑定的流程" min-width="180">
      <template #default="{ row }">
        <div v-if="(row as Dataset).usedBy?.length" class="tag-line">
          <el-tag v-for="u in (row as Dataset).usedBy" :key="u.flowId" size="small" effect="plain" disable-transitions>
            {{ u.flowName }}
          </el-tag>
        </div>
        <span v-else class="muted">—</span>
      </template>
    </el-table-column>
    <el-table-column label="更新时间" width="170">
      <template #default="{ row }">
        <span class="num">{{ formatTime((row as Dataset).updatedAt) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="180" fixed="right">
      <template #default="{ row }">
        <el-button link type="primary" @click="openEdit(row as Dataset)">编辑</el-button>
        <el-button link type="primary" tag="a" :href="datasetsApi.csvUrl((row as Dataset).id, true)">下载</el-button>
        <el-button link type="danger" @click="remove(row as Dataset)">删除</el-button>
      </template>
    </el-table-column>
  </el-table>
  <DatasetDialog v-model="dialogVisible" :dataset-id="editingId" @saved="load" />
</template>

<style scoped>
.ds-source {
  font-size: 12px;
}
.tag-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
