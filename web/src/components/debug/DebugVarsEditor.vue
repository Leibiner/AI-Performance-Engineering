<script setup lang="ts">
import { computed } from 'vue'
import { useDebugContext } from '../../composables/useDebugContext'
import KeyValueEditor from '../KeyValueEditor.vue'

// 当前环境的变量"当前值"。接口页放在"环境变量"标签页里，流程试跑放在弹层里，内容同一份。
const { varRows, initialVars, resetVars, environment } = useDebugContext()
const initialCount = computed(() => Object.keys(initialVars.value).length)
</script>

<template>
  <div class="debug-vars">
    <template v-if="environment">
      <p class="form-hint">
        「{{ environment.name }}」的变量当前值，接口里的 <code v-pre>{{变量名}}</code> 按它替换。
        发送或试跑后，提取到的变量会自动更新到这里，下一个请求直接能用。
        初始值在被测环境里维护（{{ initialCount }} 个），压测从初始值开始，不受这里影响。
      </p>
      <KeyValueEditor v-model="varRows" key-placeholder="变量名" value-placeholder="当前值" add-text="添加变量" />
      <div class="debug-vars-tools">
        <el-button size="small" text type="primary" @click="resetVars">恢复为环境初始值</el-button>
        <router-link class="debug-vars-link" to="/environments">编辑初始值</router-link>
      </div>
    </template>
    <p v-else class="form-hint">先选择调试环境。</p>
  </div>
</template>

<style scoped>
.debug-vars .form-hint {
  margin: 0 0 10px;
}
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
