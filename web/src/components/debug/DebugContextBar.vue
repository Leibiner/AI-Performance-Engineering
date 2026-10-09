<script setup lang="ts">
import { onMounted } from 'vue'
import { useDebugContext } from '../../composables/useDebugContext'
import EnvTypeTag from '../EnvTypeTag.vue'
import KeyValueEditor from '../KeyValueEditor.vue'

// 调试上下文栏：选被测环境、确认生产、填初始变量。接口页和流程试跑共用，状态在 useDebugContext 里跨页面保留。
const { envId, varRows, varCount, prodConfirmed, environments, environment, loaded, loadEnvironments } = useDebugContext()

onMounted(() => {
  if (!loaded.value) void loadEnvironments()
})
</script>

<template>
  <div class="debug-ctx">
    <span class="debug-ctx-label">被测环境</span>
    <el-select
      v-model="envId"
      placeholder="选择被测环境"
      style="width: 220px"
      no-data-text="还没有被测环境，先到“被测环境”页面新建"
    >
      <el-option v-for="e in environments" :key="e.id" :label="e.name" :value="e.id">
        <span class="env-option">
          <span>{{ e.name }}</span>
          <EnvTypeTag :type="e.type" />
        </span>
      </el-option>
    </el-select>
    <template v-if="environment">
      <EnvTypeTag :type="environment.type" />
      <span class="mono muted debug-ctx-url">{{ environment.baseUrl }}</span>
      <el-checkbox v-if="environment.type === 'prod'" v-model="prodConfirmed" class="debug-ctx-prod">
        我确认向这个生产环境真实地发出请求
      </el-checkbox>
    </template>

    <el-popover placement="bottom-start" :width="560" trigger="click">
      <template #reference>
        <el-button text bg class="debug-ctx-vars">
          变量
          <span v-if="varCount" class="debug-ctx-count">{{ varCount }}</span>
        </el-button>
      </template>
      <div class="debug-vars">
        <p class="form-hint">
          调试时的初始变量。接口里的 <code v-pre>{{变量名}}</code> 按这里的值替换；试跑流程时，前面步骤提取到的同名变量会覆盖它。
        </p>
        <KeyValueEditor v-model="varRows" key-placeholder="变量名" value-placeholder="值" add-text="添加变量" />
      </div>
    </el-popover>
  </div>
</template>

<style scoped>
.debug-ctx {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  min-height: 32px;
}
.debug-ctx-label {
  color: var(--ink-muted);
  font-size: 13px;
}
.debug-ctx-url {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.debug-ctx-prod {
  margin-left: 4px;
  --el-checkbox-checked-text-color: var(--el-color-danger);
  --el-checkbox-checked-bg-color: var(--el-color-danger);
  --el-checkbox-checked-input-border-color: var(--el-color-danger);
}
.debug-ctx-vars {
  margin-left: auto;
}
.debug-ctx-count {
  display: inline-block;
  min-width: 18px;
  margin-left: 6px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}
.env-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.debug-vars .form-hint {
  margin: 0 0 10px;
}
</style>
