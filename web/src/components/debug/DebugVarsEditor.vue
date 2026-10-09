<script setup lang="ts">
import { useDebugContext } from '../../composables/useDebugContext'
import KeyValueEditor from '../KeyValueEditor.vue'

// 调试用的初始变量。接口页放在"调试变量"标签页里，流程试跑放在弹层里，内容同一份。
const { varRows } = useDebugContext()
</script>

<template>
  <div class="debug-vars">
    <p class="form-hint">
      调试时的初始变量，不随接口保存。接口里的 <code v-pre>{{变量名}}</code> 按这里的值替换；试跑流程时，前面步骤提取到的同名变量会覆盖它。
    </p>
    <KeyValueEditor v-model="varRows" key-placeholder="变量名" value-placeholder="值" add-text="添加变量" />
  </div>
</template>

<style scoped>
.debug-vars .form-hint {
  margin: 0 0 10px;
}
</style>
