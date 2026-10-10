<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, Upload } from '@element-plus/icons-vue'
import PageHeader from '../components/PageHeader.vue'
import DatasetsPanel from '../components/data/DatasetsPanel.vue'
import FilesPanel from '../components/data/FilesPanel.vue'

// 不把标签页写回地址：App.vue 以完整地址为 key，改 query 会重建整个页面
const route = useRoute()
const tab = ref<'datasets' | 'files'>(route.query.tab === 'files' ? 'files' : 'datasets')
const datasetsPanel = ref<InstanceType<typeof DatasetsPanel>>()
const filesPanel = ref<InstanceType<typeof FilesPanel>>()
</script>

<template>
  <div class="page">
    <PageHeader>
      <el-button v-if="tab === 'datasets'" type="primary" :icon="Plus" @click="datasetsPanel?.openCreate()">新建数据集</el-button>
      <el-button v-else type="primary" :icon="Upload" :loading="filesPanel?.uploading" @click="filesPanel?.pickUpload()">
        上传文件
      </el-button>
    </PageHeader>
    <div class="panel">
      <el-tabs v-model="tab">
        <el-tab-pane name="datasets" label="数据集">
          <DatasetsPanel ref="datasetsPanel" />
        </el-tab-pane>
        <el-tab-pane name="files" label="文件">
          <FilesPanel ref="filesPanel" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>
