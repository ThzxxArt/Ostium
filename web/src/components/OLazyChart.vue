<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue'
import type { TrafficPoint } from '@/api/types'

const props = withDefaults(
  defineProps<{
    series: TrafficPoint[]
    height?: number
    showUpload?: boolean
    showDownload?: boolean
  }>(),
  { height: 280, showUpload: true, showDownload: true },
)

const OTrafficChart = defineAsyncComponent(() => import('./OTrafficChart.vue'))
const root = ref<HTMLElement | null>(null)
const visible = ref(false)
let observer: IntersectionObserver | null = null

onMounted(() => {
  if (!('IntersectionObserver' in window)) {
    visible.value = true
    return
  }
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        visible.value = true
        observer?.disconnect()
        observer = null
      }
    },
    { rootMargin: '240px 0px' },
  )
  if (root.value) observer.observe(root.value)
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div ref="root" class="lazy-chart" :style="{ minHeight: `${props.height}px` }">
    <component
      :is="OTrafficChart"
      v-if="visible"
      :series="props.series"
      :height="props.height"
      :show-upload="props.showUpload"
      :show-download="props.showDownload"
    />
    <div v-else class="placeholder" aria-hidden="true">
      <span class="line" />
      <span class="line short" />
    </div>
  </div>
</template>

<style scoped>
.lazy-chart {
  width: 100%;
}
.placeholder {
  height: 100%;
  min-height: inherit;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.line {
  width: 56%;
  height: 2px;
  border-radius: 4px;
  background: linear-gradient(90deg, transparent, var(--border-strong), transparent);
}
.line.short {
  width: 30%;
}
</style>
