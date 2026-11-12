<script setup lang="ts">
import type { Component } from 'vue'

withDefaults(
  defineProps<{
    title?: string
    description?: string
    icon?: Component
    flush?: boolean
    padding?: 'normal' | 'compact' | 'none'
  }>(),
  { padding: 'normal' },
)
</script>

<template>
  <section class="section-card" :class="[`padding-${padding}`]">
    <header v-if="title || $slots.header || $slots.actions" class="header">
      <div class="heading">
        <span v-if="icon" class="icon"
          ><component :is="icon" :size="18" :stroke-width="1.6"
        /></span>
        <div v-if="title || description" class="copy">
          <h2 v-if="title">{{ title }}</h2>
          <p v-if="description" class="o-muted o-small">{{ description }}</p>
        </div>
        <slot name="header" />
      </div>
      <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
    </header>
    <div class="content" :class="{ flush }">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="footer"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.section-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-1);
  overflow: hidden;
}
.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px 0;
  flex-wrap: wrap;
}
.heading {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  min-width: 0;
}
.icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  color: var(--accent);
  background: var(--accent-soft);
  flex: none;
}
h2 {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
}
p {
  margin-top: 2px;
}
.actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.content {
  padding: 18px 22px 22px;
}
.content.flush {
  padding: 12px 0 0;
}
.padding-compact .content {
  padding: 12px 18px 18px;
}
.padding-none .content {
  padding: 0;
}
.footer {
  padding: 12px 22px;
  border-top: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface-2) 40%, transparent);
}
@media (max-width: 767px) {
  .header {
    padding: 16px 16px 0;
  }
  .content {
    padding: 14px 16px 18px;
  }
}
</style>
