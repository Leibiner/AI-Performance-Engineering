<script setup lang="ts">
import { useDebugContext } from '../../composables/useDebugContext'
import KeyValueEditor from '../KeyValueEditor.vue'

const { varRows, resetVars, environment } = useDebugContext()
</script>

<template>
  <div class="debug-vars">
    <template v-if="environment">
      <KeyValueEditor v-model="varRows" key-placeholder="变量名" value-placeholder="当前值" add-text="添加变量" />
      <div class="debug-vars-tools">
        <el-button size="small" text type="primary" @click="resetVars">重置为初始值</el-button>
        <router-link class="debug-vars-link" to="/environments">编辑初始值</router-link>
      </div>
    </template>
    <p v-else class="muted">未选择环境</p>
  </div>
</template>

<style scoped>
.debug-vars-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}
.debug-vars-link {
  color: var(--el-color-primary);
  font-size: 12px;
  text-decoration: none;
}
</style>
