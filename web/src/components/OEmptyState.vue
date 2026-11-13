<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import { Inbox } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(
  defineProps<{
    title?: string
    description?: string
    icon?: Component
    compact?: boolean
  }>(),
  { compact: false },
)

const resolvedIcon = computed(() => props.icon ?? Inbox)
const { t } = useI18n()
</script>

<template>
  <div class="empty" :class="{ compact }">
    <div class="art" aria-hidden="true">
      <div class="ring ring-a" />
      <div class="ring ring-b" />
      <div class="core">
        <component :is="resolvedIcon" :size="compact ? 20 : 26" :stroke-width="1.5" />
      </div>
    </div>
    <h3>{{ title || t('common.empty') }}</h3>
    <p v-if="description">{{ description }}</p>
    <div v-if="$slots.default" class="actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 48px 24px;
  gap: 8px;
}
.empty.compact {
  padding: 28px 16px;
}
.art {
  position: relative;
  width: 92px;
  height: 92px;
  display: grid;
  place-items: center;
  margin-bottom: 4px;
}
.compact .art {
  width: 64px;
  height: 64px;
}
.ring {
  position: absolute;
  border-radius: 50%;
  border: 1px solid var(--border);
}
.ring-a {
  inset: 0;
  border-color: color-mix(in srgb, var(--accent) 24%, transparent);
}
.ring-b {
  inset: 14px;
  border-style: dashed;
  border-color: var(--border-strong);
}
.core {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: var(--accent);
  background: var(--accent-soft);
  box-shadow: 0 0 28px color-mix(in srgb, var(--accent) 18%, transparent);
}
h3 {
  font-size: 14.5px;
  font-weight: 600;
}
p {
  max-width: 440px;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.6;
}
.actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}
</style>
