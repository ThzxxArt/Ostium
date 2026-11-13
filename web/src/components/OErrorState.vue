<script setup lang="ts">
import { AlertTriangle, RotateCw } from '@lucide/vue'
import { NButton } from 'naive-ui'
import { useI18n } from 'vue-i18n'

defineProps<{
  title?: string
  message?: string
}>()

defineEmits<{ retry: [] }>()
const { t } = useI18n()
</script>

<template>
  <div class="error-state" role="alert">
    <div class="icon"><AlertTriangle :size="22" :stroke-width="1.6" /></div>
    <h3>{{ title || t('common.error') }}</h3>
    <p>{{ message || t('common.error_hint') }}</p>
    <div class="actions">
      <slot name="actions">
        <NButton secondary size="small" @click="$emit('retry')">
          <template #icon><RotateCw :size="15" /></template>
          {{ t('common.retry') }}
        </NButton>
      </slot>
    </div>
    <details v-if="$slots.details" class="details">
      <summary>{{ t('common.details') }}</summary>
      <slot name="details" />
    </details>
  </div>
</template>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 36px 22px;
  gap: 8px;
}
.icon {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--danger);
  background: var(--danger-soft);
  border: 1px solid color-mix(in srgb, var(--danger) 25%, transparent);
}
h3 {
  margin-top: 4px;
  font-size: 15px;
  font-weight: 600;
}
p {
  max-width: 500px;
  color: var(--text-2);
  font-size: 13px;
}
.actions {
  margin-top: 8px;
}
.details {
  margin-top: 12px;
  width: 100%;
  max-width: 640px;
  text-align: left;
  color: var(--text-2);
  font-size: 12px;
}
summary {
  cursor: pointer;
}
</style>
