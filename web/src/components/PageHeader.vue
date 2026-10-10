<script setup lang="ts">
defineProps<{ description?: string }>()
</script>

<template>
  <div v-if="description || $slots.description || $slots.default" class="page-header">
    <p v-if="description || $slots.description" class="page-desc">
      <slot name="description">{{ description }}</slot>
    </p>
    <div class="page-actions"><slot /></div>
  </div>
</template>
