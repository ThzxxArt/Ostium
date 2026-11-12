<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, CircleAlert, CircleX, CircleDot, LoaderCircle } from 'lucide-vue-next'
import { statusTone } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    status: string
    label?: string
    pulse?: boolean
    size?: 'sm' | 'md'
  }>(),
  { size: 'md' },
)

const tone = computed(() => statusTone(props.status))
const icon = computed(() => {
  if (props.status === 'connecting' || props.status === 'pending') return LoaderCircle
  if (tone.value === 'success') return CircleCheck
  if (tone.value === 'warning') return CircleAlert
  if (tone.value === 'danger') return CircleX
  return CircleDot
})
</script>

<template>
  <span class="pill" :class="[`tone-${tone}`, `size-${size}`, { pulse }]" role="status">
    <component
      :is="icon"
      :size="size === 'sm' ? 12 : 14"
      :stroke-width="2"
      :class="{ spin: status === 'connecting' || status === 'pending' }"
    />
    <span>{{ label || status }}</span>
  </span>
</template>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  border: 1px solid currentColor;
  padding: 3px 10px;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
  background: transparent;
}
.size-sm {
  padding: 1px 8px;
  font-size: 10.5px;
}
.tone-success {
  color: var(--success);
  background: var(--success-soft);
}
.tone-warning {
  color: var(--warning);
  background: var(--warning-soft);
}
.tone-danger {
  color: var(--danger);
  background: var(--danger-soft);
}
.tone-info {
  color: var(--info);
  background: var(--accent-soft-2);
}
.tone-neutral {
  color: var(--text-2);
  background: var(--surface-2);
}
.pulse {
  box-shadow: 0 0 0 0 currentColor;
  animation: breathe 2.4s var(--ease) infinite;
}
@keyframes breathe {
  0%,
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
  50% {
    box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 12%, transparent);
  }
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .pulse,
  .spin {
    animation: none;
  }
}
</style>
