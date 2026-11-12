<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import type { EChartsOption } from 'echarts'
import { useAppStore } from '@/stores/app'
import { formatBytes, formatDay } from '@/utils/format'
import type { TrafficPoint } from '@/api/types'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

const props = withDefaults(
  defineProps<{
    series: TrafficPoint[]
    height?: number
    showUpload?: boolean
    showDownload?: boolean
  }>(),
  { height: 280, showUpload: true, showDownload: true },
)

const app = useAppStore()

const option = computed<EChartsOption>(() => {
  const text = app.isDark ? '#6F819B' : '#64748B'
  const grid = app.isDark ? 'rgba(148,163,184,.12)' : 'rgba(15,23,42,.08)'
  const up = app.isDark ? '#5EEAD4' : '#0F766E'
  const down = app.isDark ? '#60A5FA' : '#2563EB'
  return {
    animationDuration: 300,
    grid: { left: 8, right: 10, top: 18, bottom: 6, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: app.isDark ? 'rgba(13,21,36,.94)' : 'rgba(255,255,255,.97)',
      borderColor: app.isDark ? 'rgba(148,163,184,.22)' : 'rgba(15,23,42,.12)',
      textStyle: { color: app.isDark ? '#EDF3FF' : '#0F172A', fontSize: 12 },
      formatter: (params: unknown) => {
        const items = params as Array<{
          axisValue: string
          seriesName: string
          value: number
          color: string
        }>
        if (!items?.length) return ''
        const lines = [`<div style="opacity:.65;margin-bottom:4px">${items[0].axisValue}</div>`]
        for (const item of items) {
          lines.push(
            `<div style="display:flex;justify-content:space-between;gap:18px"><span>${item.seriesName}</span><b>${formatBytes(item.value)}</b></div>`,
          )
        }
        return lines.join('')
      },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: props.series.map((point) => formatDay(point.day)),
      axisLine: { lineStyle: { color: grid } },
      axisTick: { show: false },
      axisLabel: { color: text, fontSize: 10.5, margin: 10 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: grid, type: 'dashed' } },
      axisLabel: {
        color: text,
        fontSize: 10.5,
        formatter: (value: number) => formatBytes(value, 0),
      },
    },
    series: [
      props.showDownload
        ? {
            name: 'Download',
            type: 'line',
            smooth: 0.35,
            symbol: 'none',
            data: props.series.map((point) => point.down),
            lineStyle: { width: 2, color: down },
            areaStyle: {
              opacity: 0.16,
              color: down,
            },
          }
        : undefined,
      props.showUpload
        ? {
            name: 'Upload',
            type: 'line',
            smooth: 0.35,
            symbol: 'none',
            data: props.series.map((point) => point.up),
            lineStyle: { width: 2, color: up },
            areaStyle: {
              opacity: 0.1,
              color: up,
            },
          }
        : undefined,
    ].filter(Boolean) as EChartsOption['series'],
  }
})
</script>

<template>
  <div class="chart-wrap" :style="{ height: `${height}px` }">
    <VChart v-if="series.length" :option="option" autoresize />
    <div v-else class="empty">
      <span class="line" />
      <span class="line short" />
      <span class="hint">No traffic data yet</span>
    </div>
  </div>
</template>

<style scoped>
.chart-wrap {
  width: 100%;
  min-height: 180px;
}
.empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.line {
  width: 60%;
  height: 2px;
  border-radius: 4px;
  background: linear-gradient(90deg, transparent, var(--border-strong), transparent);
}
.line.short {
  width: 35%;
}
.hint {
  color: var(--text-3);
  font-size: 12px;
}
</style>
