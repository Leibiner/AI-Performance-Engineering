<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div class="page-header">
    <div>
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="description || $slots.description" class="page-desc">
        <slot name="description">{{ description }}</slot>
      </p>
    </div>
    <div class="page-actions"><slot /></div>
  </div>
</template>
