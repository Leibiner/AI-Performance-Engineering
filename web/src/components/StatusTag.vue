<script setup lang="ts">
import type { RunStatus } from '../api'

defineProps<{ status: RunStatus }>()
</script>

<template>
  <el-tag v-if="status === 'running'" type="primary" effect="dark" size="small" round>运行中</el-tag>
  <el-tag v-else type="info" effect="plain" size="small" round>已结束</el-tag>
</template>
