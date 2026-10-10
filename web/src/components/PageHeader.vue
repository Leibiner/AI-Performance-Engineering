<template>
  <div class="page-header">
    <div v-if="$slots.context" class="page-context"><slot name="context" /></div>
    <div v-if="$slots.default" class="page-actions"><slot /></div>
  </div>
</template>
