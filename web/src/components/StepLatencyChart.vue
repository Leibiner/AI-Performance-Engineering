<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, type BarSeriesOption } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  type GridComponentOption,
  type LegendComponentOption,
  type TooltipComponentOption,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { StepMetrics } from '../api'
import { formatNumber } from '../utils/format'

// 按需引入 ECharts：只注册柱状图用到的部分
echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

type ChartOption = echarts.ComposeOption<
  BarSeriesOption | GridComponentOption | LegendComponentOption | TooltipComponentOption
>

const props = defineProps<{ steps: StepMetrics[] }>()

// p50 / p95 / p99 是同一个指标的三个有序分位，用同一色相由浅到深，而不是三种不相干的颜色
const SERIES = [
  { key: 'p50', name: 'p50', color: '#86b6ef' },
  { key: 'p95', name: 'p95', color: '#2a78d6' },
  { key: 'p99', name: 'p99', color: '#104281' },
] as const

const INK = '#52514e'
const MUTED = '#898781'
const GRID = '#e6e8ec'

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | undefined
let observer: ResizeObserver | undefined

function buildOption(): ChartOption {
  const multiFlow = new Set(props.steps.map((s) => s.flowKey)).size > 1
  const categories = props.steps.map((s) => {
    const name = s.phase === 'init' ? `初始化 · ${s.stepName}` : s.stepName
    return multiFlow ? `${s.flowName} / ${name}` : name
  })
  return {
    animationDuration: 300,
    textStyle: { fontFamily: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif' },
    color: SERIES.map((s) => s.color),
    legend: { top: 0, left: 0, itemWidth: 12, itemHeight: 12, itemGap: 18, textStyle: { color: INK } },
    grid: { top: 48, left: 8, right: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(0, 0, 0, 0.04)' } },
      valueFormatter: (value) => (typeof value === 'number' ? `${formatNumber(value, 1)} ms` : '—'),
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#c3c7ce' } },
      axisLabel: { color: INK, interval: 0, width: 140, overflow: 'truncate', hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      name: '响应时间（ms）',
      nameTextStyle: { color: MUTED, align: 'left' },
      axisLabel: { color: MUTED },
      splitLine: { lineStyle: { color: GRID, type: 'solid' } },
    },
    series: SERIES.map((s) => ({
      type: 'bar',
      name: s.name,
      // 没有样本的步骤值为 null，ECharts 会留空不画
      data: props.steps.map((step) => step[s.key]),
      barMaxWidth: 24,
      barGap: '12%',
      itemStyle: { borderRadius: [4, 4, 0, 0] },
      // 不在柱顶标数值：相邻的柱子只有 24px 宽，数字会互相压住。具体数值看上方的表格和悬浮提示
      emphasis: { focus: 'series' },
    })),
  }
}

function render(): void {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  chart.setOption(buildOption(), true)
}

onMounted(() => {
  render()
  if (el.value) {
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(el.value)
  }
})
watch(() => props.steps, render, { deep: true })
onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = undefined
})
</script>

<template>
  <div ref="el" class="chart" role="img" aria-label="分步骤响应时间柱状图：p50、p95、p99" />
</template>

<style scoped>
.chart {
  width: 100%;
  height: 340px;
}
</style>
