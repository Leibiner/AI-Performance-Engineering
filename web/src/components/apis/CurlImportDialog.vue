<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { curlToApi, parseCurl, type CurlImport } from '../../utils/curl'

// 粘贴 curl 命令 → 预览 → 填进编辑器。不直接保存，让人先改名字、补期望和提取规则。
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ imported: [result: CurlImport] }>()

const text = ref('')
const parsed = ref<CurlImport | null>(null)
const problem = ref<string | null>(null)

watch(visible, (open) => {
  if (open) {
    text.value = ''
    parsed.value = null
    problem.value = null
  }
})

watch(text, (value) => {
  if (!value.trim()) {
    parsed.value = null
    problem.value = null
    return
  }
  try {
    parsed.value = curlToApi(parseCurl(value))
    problem.value = null
  } catch (e) {
    parsed.value = null
    problem.value = e instanceof Error ? e.message : String(e)
  }
})

const headerRows = computed(() => Object.entries(parsed.value?.input.headers ?? {}))

function confirm(): void {
  if (!parsed.value) return
  emit('imported', parsed.value)
  visible.value = false
}
</script>

<template>
  <el-dialog v-model="visible" title="从 cURL 导入" width="760px" top="8vh" :close-on-click-modal="false">
    <el-input
      v-model="text"
      type="textarea"
      :rows="7"
      class="mono"
      placeholder="粘贴 curl 命令。浏览器开发者工具的“复制为 cURL”、Postman 和 Apifox 导出的命令都可以。"
    />
    <el-alert v-if="problem" type="error" :closable="false" show-icon :title="problem" class="curl-problem" />

    <div v-if="parsed" class="curl-preview">
      <div class="curl-line">
        <strong>{{ parsed.input.method }}</strong>
        <span class="mono">{{ parsed.input.path }}</span>
      </div>
      <div class="form-hint">
        原命令的地址是 <span class="mono">{{ parsed.origin }}</span>，对应被测环境的基础地址；这里只导入路径部分。发送前请确认所选被测环境指向同一个地址。
      </div>
      <table v-if="headerRows.length" class="curl-table">
        <tbody>
          <tr v-for="[name, value] in headerRows" :key="name">
            <th>{{ name }}</th>
            <td class="mono">{{ value }}</td>
          </tr>
        </tbody>
      </table>
      <pre v-if="parsed.input.body !== null" class="curl-body">{{ parsed.input.body }}</pre>
      <div class="form-hint">期望状态码默认 200；“期望包含的文本”和“变量提取”需要在编辑器里补充。</div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!parsed" @click="confirm">填入编辑器</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.curl-problem {
  margin-top: 10px;
}
.curl-preview {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid var(--hairline);
  border-radius: 8px;
  background: #fafbfc;
}
.curl-line {
  display: flex;
  gap: 10px;
  margin-bottom: 4px;
  word-break: break-all;
}
.curl-table {
  width: 100%;
  margin: 10px 0;
  border-collapse: collapse;
  font-size: 13px;
}
.curl-table th,
.curl-table td {
  padding: 4px 8px;
  border-bottom: 1px solid var(--hairline);
  text-align: left;
  word-break: break-all;
}
.curl-table th {
  width: 200px;
  font-weight: 500;
}
.curl-body {
  max-height: 160px;
  margin: 8px 0;
  padding: 8px 10px;
  overflow: auto;
  border-radius: 6px;
  background: #fff;
  border: 1px solid var(--hairline);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
