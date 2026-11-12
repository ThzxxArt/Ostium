<script setup lang="ts">
import { computed } from 'vue'
import { NModal } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const { t } = useI18n()
const show = computed({
  get: () => app.shortcutsOpen,
  set: (value) => (app.shortcutsOpen = value),
})

const rows = computed(() => [
  { keys: ['⌘', 'K'], label: t('shortcuts.command') },
  { keys: ['G', 'D'], label: t('shortcuts.go') },
  { keys: ['C'], label: t('shortcuts.connect') },
  { keys: ['/'], label: t('shortcuts.search') },
  { keys: ['?'], label: t('shortcuts.help') },
  { keys: ['Esc'], label: t('shortcuts.close') },
])
</script>

<template>
  <NModal v-model:show="show" preset="card" style="max-width: 460px" :bordered="false">
    <template #header>{{ t('shortcuts.title') }}</template>
    <ul class="shortcuts">
      <li v-for="row in rows" :key="row.label">
        <span>{{ row.label }}</span>
        <span class="keys">
          <kbd v-for="key in row.keys" :key="key">{{ key }}</kbd>
        </span>
      </li>
    </ul>
  </NModal>
</template>

<style scoped>
.shortcuts {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 9px 2px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
li:last-child {
  border-bottom: 0;
}
.keys {
  display: flex;
  gap: 5px;
}
kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 22px;
  padding: 0 6px;
  border-radius: 6px;
  border: 1px solid var(--border-strong);
  background: var(--surface-2);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: 10.5px;
}
</style>
