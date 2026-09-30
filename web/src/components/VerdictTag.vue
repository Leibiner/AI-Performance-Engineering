<script setup lang="ts">
import { computed } from 'vue'
import type { Verdict } from '../api'
import { VERDICTS } from '../utils/verdict'
import { DASH } from '../utils/format'

const props = defineProps<{ verdict: Verdict | null | undefined }>()
const meta = computed(() => (props.verdict ? VERDICTS[props.verdict] : null))
</script>

<template>
  <span
    v-if="meta"
    class="verdict-tag"
    :style="{ color: meta.color, background: meta.soft, borderColor: meta.color }"
    :title="meta.description"
  >
    <span class="verdict-dot" :style="{ background: meta.color }" />{{ meta.label }}
  </span>
  <span v-else class="muted">{{ DASH }}</span>
</template>

<style scoped>
.verdict-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 1px solid;
  border-radius: 11px;
  font-size: 12px;
  font-weight: 600;
  line-height: 20px;
  white-space: nowrap;
}
.verdict-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
</style>
