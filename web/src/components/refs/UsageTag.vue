<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { Usage } from '../../api'
import { REF_KINDS, usageSummary } from '../../utils/references'

const props = defineProps<{ usages: Usage[] }>()
const router = useRouter()
const summary = computed(() => usageSummary(props.usages))
</script>

<template>
  <el-popover v-if="usages.length" placement="bottom-start" :width="360" trigger="hover">
    <template #reference>
      <span class="usage-tag">{{ summary }}</span>
    </template>
    <ul class="usage-list">
      <li v-for="u in usages" :key="`${u.kind}-${u.id}`">
        <span class="muted">{{ REF_KINDS[u.kind].label }}</span>
        <a class="dep-link" @click="router.push(REF_KINDS[u.kind].open(u.id))">{{ u.name }}</a>
        <span class="muted">{{ u.where.join('、') }}</span>
      </li>
    </ul>
  </el-popover>
</template>

<style scoped>
.usage-tag {
  flex-shrink: 0;
  color: var(--el-color-primary);
  font-size: 12px;
  white-space: nowrap;
  cursor: default;
}
.usage-list {
  margin: 0;
  padding: 0;
  list-style: none;
  line-height: 1.9;
}
.usage-list li {
  display: flex;
  gap: 8px;
}
.usage-list .muted {
  font-size: 12px;
}
</style>
