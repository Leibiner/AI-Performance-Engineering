<script setup lang="ts">
import { computed } from 'vue'
import type { BrokenRef } from '../../api'
import { brokenSummary } from '../../utils/references'

const props = defineProps<{ refs: BrokenRef[] }>()
const count = computed(() => props.refs.reduce((n, r) => n + r.where.length, 0))
</script>

<template>
  <el-tooltip v-if="refs.length" :content="brokenSummary(refs)" placement="top">
    <el-tag size="small" type="danger" effect="plain" class="broken-tag" disable-transitions>失效 {{ count }}</el-tag>
  </el-tooltip>
</template>

<style scoped>
.broken-tag {
  flex-shrink: 0;
  margin-left: 6px;
}
</style>
