<script setup lang="ts">
import { computed } from 'vue'
import type { EnvType } from '../api'
import { ENV_TYPES } from '../utils/env'

// 被测环境的类型标签。类型为空（旧的运行记录）时不显示。
const props = defineProps<{ type: EnvType | null | undefined }>()
const meta = computed(() => (props.type ? (ENV_TYPES[props.type] ?? null) : null))
</script>

<template>
  <el-tag v-if="meta" :type="meta.tag" :effect="meta.effect" size="small" class="env-type-tag">{{ meta.label }}</el-tag>
</template>

<style scoped>
.env-type-tag {
  flex-shrink: 0;
  vertical-align: middle;
}
</style>
