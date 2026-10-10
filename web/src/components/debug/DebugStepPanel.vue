<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DebugStep } from '../../api'
import { EXTRACT_FROM_LABELS, STEP_STATUS, checksSummary, formatChars, tryPrettyJson } from '../../utils/debug'
import { formatBytes, formatMs } from '../../utils/format'
import { STATUS_STYLE, statusKind, statusLabel } from '../../utils/http-status'

const props = defineProps<{ step: DebugStep }>()

const tab = ref('body')
const pretty = ref(true)

const kind = computed(() => statusKind(props.step.response?.status))
const pill = computed(() => STATUS_STYLE[kind.value])
const prettyBody = computed(() => tryPrettyJson(props.step.response?.body))
const bodyText = computed(() => (pretty.value && prettyBody.value ? prettyBody.value : (props.step.response?.body ?? '')))
const summary = computed(() => checksSummary(props.step))
const notRun = computed(() => props.step.status === 'skipped' || props.step.status === 'error')

interface Row {
  name: string
  value: string
}
function rows(record: Record<string, string> | null | undefined): Row[] {
  return Object.entries(record ?? {}).map(([name, value]) => ({ name, value }))
}
const responseHeaders = computed(() => rows(props.step.response?.headers))
const requestHeaders = computed(() => rows(props.step.request?.headers))
const varRows = computed(() => rows(props.step.vars))
const requestForm = computed(() => props.step.request?.form ?? null)
const formTitle = computed(() => (props.step.request?.bodyType === 'multipart' ? 'form-data' : 'x-www-form-urlencoded'))

const timingRows = computed(() => {
  const t = props.step.timings
  if (!t) return []
  return [
    { label: '阻塞（等待可用连接）', value: t.blockedMs },
    { label: 'DNS 解析', value: t.lookingUpMs },
    { label: '建立 TCP 连接', value: t.connectingMs },
    { label: 'TLS 握手', value: t.tlsMs },
    { label: '发送请求', value: t.sendingMs },
    { label: '等待响应（首字节）', value: t.waitingMs },
    { label: '接收响应', value: t.receivingMs },
  ]
})
</script>

<template>
  <div class="step-panel">
    <el-alert
      v-if="notRun"
      :type="step.status === 'error' ? 'error' : 'info'"
      :closable="false"
      show-icon
      :title="step.status === 'error' ? '执行这一步时出错' : '这一步没有执行'"
      :description="step.error ?? ''"
    />

    <template v-else-if="step.response">
      <div class="status-line">
        <span class="status-pill" :style="{ color: pill.color, background: pill.soft }">
          {{ statusLabel(step.response.status, step.response.statusText) }}
        </span>
        <span class="status-meta">
          <span class="num">{{ formatMs(step.timings?.durationMs) }}</span>
          <span class="dot">·</span>
          <span>{{ step.response.bodyOmitted || step.response.bodyLength ? formatChars(step.response.bodyLength) : '空响应体' }}</span>
        </span>
        <el-tag :type="STEP_STATUS[step.status].tag" effect="dark" size="small" class="status-checks">
          {{ summary.total === 0 ? STEP_STATUS[step.status].label : `检查 ${summary.passed} / ${summary.total} 通过` }}
        </el-tag>
        <span v-if="step.error" class="status-error">{{ step.error }}</span>
      </div>

      <el-tabs v-model="tab" class="step-tabs">
        <el-tab-pane name="body" label="响应体">
          <div v-if="step.response.bodyOmitted" class="body-note">
            响应不是文本（{{ step.response.contentType || '未知类型' }}），只显示长度：{{ formatChars(step.response.bodyLength) }}。
          </div>
          <template v-else>
            <div class="body-tools">
              <el-radio-group v-if="prettyBody" v-model="pretty" size="small">
                <el-radio-button :value="true">格式化 JSON</el-radio-button>
                <el-radio-button :value="false">原文</el-radio-button>
              </el-radio-group>
              <span v-if="step.response.bodyTruncated" class="body-truncated">只显示前 64 KB，完整长度 {{ formatChars(step.response.bodyLength) }}</span>
              <span v-if="step.response.contentType" class="muted mono body-ctype">{{ step.response.contentType }}</span>
            </div>
            <pre v-if="bodyText" class="code-block">{{ bodyText }}</pre>
            <div v-else class="body-note">响应体为空。</div>
          </template>
        </el-tab-pane>

        <el-tab-pane name="headers">
          <template #label>响应头<span class="tab-count">{{ responseHeaders.length }}</span></template>
          <table class="kv-table">
            <tbody>
              <tr v-for="row in responseHeaders" :key="row.name">
                <th>{{ row.name }}</th>
                <td class="mono">{{ row.value }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="step.response.finalUrl && step.request && step.response.finalUrl !== step.request.url" class="body-note">
            经过重定向，最终地址：<span class="mono">{{ step.response.finalUrl }}</span>
          </div>
        </el-tab-pane>

        <el-tab-pane name="checks">
          <template #label>
            检查<span class="tab-count" :class="{ 'is-bad': summary.passed < summary.total }">{{ summary.passed }}/{{ summary.total }}</span>
          </template>
          <ul class="check-list">
            <li v-for="c in step.checks" :key="c.name" :class="c.ok ? 'is-ok' : 'is-bad'">
              <span class="check-mark">{{ c.ok ? '✓' : '✗' }}</span>
              <span class="mono">{{ c.name }}</span>
            </li>
          </ul>
        </el-tab-pane>

        <el-tab-pane name="vars">
          <template #label>变量<span class="tab-count">{{ varRows.length }}</span></template>
          <template v-if="step.extracted.length">
            <div class="sub-title">这一步的提取规则</div>
            <table class="kv-table">
              <tbody>
                <tr v-for="e in step.extracted" :key="e.var" :class="e.ok ? '' : 'is-bad'">
                  <th class="mono">{{ e.var }}</th>
                  <td>
                    <span class="muted">{{ EXTRACT_FROM_LABELS[e.from] ?? e.from }} · </span><span class="mono">{{ e.expr }}</span>
                  </td>
                  <td class="mono">{{ e.ok ? e.value : '没取到' }}</td>
                </tr>
              </tbody>
            </table>
          </template>
          <div class="sub-title">这一步之后的全部变量</div>
          <table v-if="varRows.length" class="kv-table">
            <tbody>
              <tr v-for="row in varRows" :key="row.name">
                <th class="mono">{{ row.name }}</th>
                <td class="mono">{{ row.value }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="body-note">没有变量。</div>
        </el-tab-pane>

        <el-tab-pane name="request" label="实际请求">
          <template v-if="step.request">
            <div class="req-line">
              <span class="req-method">{{ step.request.method }}</span>
              <span class="mono">{{ step.request.url }}</span>
            </div>
            <div class="sub-title">请求头（已和被测环境的公共请求头合并）</div>
            <table class="kv-table">
              <tbody>
                <tr v-for="row in requestHeaders" :key="row.name">
                  <th>{{ row.name }}</th>
                  <td class="mono">{{ row.value }}</td>
                </tr>
              </tbody>
            </table>
            <template v-if="requestForm">
              <div class="sub-title">{{ formTitle }}</div>
              <table class="kv-table">
                <tbody>
                  <tr v-for="(item, index) in requestForm" :key="index">
                    <th class="mono">{{ item.name }}</th>
                    <td v-if="item.type === 'file'">
                      <span class="mono">{{ item.fileName }}</span>
                      <span class="muted"> · {{ item.contentType }} · {{ formatBytes(item.size) }}</span>
                    </td>
                    <td v-else class="mono">{{ item.value }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
            <template v-if="step.request.body !== null">
              <div class="sub-title">{{ requestForm ? '编码后的请求体' : '请求体' }}</div>
              <pre class="code-block">{{ step.request.body }}</pre>
            </template>
          </template>
        </el-tab-pane>

        <el-tab-pane name="timings" label="耗时分解">
          <table class="kv-table timing-table">
            <tbody>
              <tr v-for="row in timingRows" :key="row.label">
                <th>{{ row.label }}</th>
                <td class="num">{{ formatMs(row.value) }}</td>
              </tr>
              <tr class="timing-total">
                <th>响应时间（发出请求到收完响应）</th>
                <td class="num">{{ formatMs(step.timings?.durationMs) }}</td>
              </tr>
            </tbody>
          </table>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<style scoped>
.status-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}
.status-pill {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 6px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.status-meta {
  color: var(--ink-muted);
  font-size: 13px;
}
.status-meta .dot {
  margin: 0 6px;
}
.status-error {
  color: var(--el-color-danger);
  font-size: 13px;
}
.step-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}
.tab-count {
  margin-left: 5px;
  color: var(--ink-muted);
  font-size: 12px;
}
.tab-count.is-bad {
  color: var(--el-color-danger);
  font-weight: 600;
}
.body-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.body-truncated {
  color: var(--el-color-warning);
  font-size: 12px;
}
.body-ctype {
  margin-left: auto;
}
.body-note {
  padding: 8px 0;
  color: var(--ink-muted);
  font-size: 13px;
}
.code-block {
  max-height: 420px;
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  background: #fafbfc;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
}
.kv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.kv-table th,
.kv-table td {
  padding: 5px 10px;
  border-bottom: 1px solid var(--hairline);
  text-align: left;
  vertical-align: top;
  word-break: break-all;
}
.kv-table th {
  width: 220px;
  color: var(--el-text-color-regular);
  font-weight: 500;
}
.kv-table tr.is-bad td,
.kv-table tr.is-bad th {
  color: var(--el-color-danger);
}
.timing-table th {
  width: 60%;
}
.timing-total th,
.timing-total td {
  border-top: 2px solid var(--hairline);
  font-weight: 600;
}
.sub-title {
  margin: 10px 0 6px;
  color: var(--ink-muted);
  font-size: 12px;
}
.sub-title:first-child {
  margin-top: 0;
}
.check-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.check-list li {
  display: flex;
  gap: 8px;
  padding: 5px 0;
  border-bottom: 1px solid var(--hairline);
}
.check-list .is-ok .check-mark {
  color: #1f8a3b;
}
.check-list .is-bad {
  color: var(--el-color-danger);
}
.check-mark {
  width: 16px;
  font-weight: 700;
}
.req-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  word-break: break-all;
}
.req-method {
  font-weight: 700;
}
</style>
