<script setup lang="ts">
import type { Component } from 'vue'

withDefaults(
  defineProps<{
    label: string
    value: string | number
    unit?: string
    hint?: string
    icon?: Component
    tone?: 'accent' | 'info' | 'success' | 'warning' | 'danger' | 'neutral'
    loading?: boolean
  }>(),
  { tone: 'accent' },
)
</script>

<template>
  <article class="stat" :class="`tone-${tone}`">
    <div class="top">
      <span class="label">{{ label }}</span>
      <span v-if="icon" class="icon"><component :is="icon" :size="17" :stroke-width="1.7" /></span>
    </div>
    <div v-if="loading" class="skeleton" aria-hidden="true" />
    <div v-else class="value o-nums">
      {{ value }}<span v-if="unit" class="unit">{{ unit }}</span>
    </div>
    <p v-if="hint" class="hint">{{ hint }}</p>
  </article>
</template>

<style scoped>
.stat {
  padding: 18px 20px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--surface);
  box-shadow: var(--shadow-1);
  min-height: 122px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
  overflow: hidden;
}
.stat::after {
  content: '';
  position: absolute;
  inset: auto -20% -60% auto;
  width: 160px;
  height: 120px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.06;
  filter: blur(24px);
  pointer-events: none;
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
  letter-spacing: 0.01em;
}
.icon {
  display: inline-flex;
  color: currentColor;
  opacity: 0.9;
}
.value {
  font-size: 27px;
  line-height: 1.15;
  font-weight: 600;
  letter-spacing: -0.03em;
  margin-top: 10px;
}
.unit {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-2);
  margin-left: 5px;
  letter-spacing: 0;
}
.hint {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-3);
}
.skeleton {
  height: 30px;
  width: 65%;
  margin-top: 10px;
  border-radius: 8px;
  background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2));
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite linear;
}
@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}
.tone-accent {
  color: var(--accent);
}
.tone-info {
  color: var(--info);
}
.tone-success {
  color: var(--success);
}
.tone-warning {
  color: var(--warning);
}
.tone-danger {
  color: var(--danger);
}
.tone-neutral {
  color: var(--text-2);
}
</style>
