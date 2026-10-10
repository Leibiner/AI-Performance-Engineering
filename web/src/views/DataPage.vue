<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import DatasetsPanel from '../components/data/DatasetsPanel.vue'
import FilesPanel from '../components/data/FilesPanel.vue'

// 不把标签页写回地址：App.vue 以完整地址为 key，改 query 会重建整个页面
const route = useRoute()
const tab = ref<'datasets' | 'files'>(route.query.tab === 'files' ? 'files' : 'datasets')
</script>

<template>
  <div class="page">
    <div class="panel">
      <el-tabs v-model="tab">
        <el-tab-pane name="datasets" label="数据集">
          <DatasetsPanel />
        </el-tab-pane>
        <el-tab-pane name="files" label="文件">
          <FilesPanel />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>
