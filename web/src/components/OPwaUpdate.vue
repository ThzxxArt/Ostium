<script setup lang="ts">
import { useRegisterSW } from '@/composables/usePwa'
import { NButton } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { RefreshCw, X } from '@lucide/vue'
import { ref } from 'vue'

const { needRefresh, updateServiceWorker } = useRegisterSW()
const { t } = useI18n()
const dismissed = ref(false)

function reload() {
  void updateServiceWorker(true)
}
</script>

<template>
  <Transition name="pwa">
    <div v-if="needRefresh && !dismissed" class="pwa-update" role="status">
      <span>{{ t('notify.new_version') }}</span>
      <NButton size="tiny" type="primary" @click="reload">
        <template #icon><RefreshCw :size="13" /></template>
        {{ t('common.refresh') }}
      </NButton>
      <button
        type="button"
        class="dismiss"
        :aria-label="t('common.close')"
        @click="dismissed = true"
      >
        <X :size="14" />
      </button>
    </div>
  </Transition>
</template>

<style scoped>
.pwa-update {
  position: fixed;
  z-index: 80;
  left: 50%;
  bottom: calc(20px + env(safe-area-inset-bottom));
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px 9px 14px;
  border-radius: 12px;
  border: 1px solid var(--border-strong);
  background: var(--surface-solid);
  box-shadow: var(--shadow-2);
  font-size: 11.5px;
  color: var(--text-2);
}
.dismiss {
  border: 0;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  display: grid;
  place-items: center;
}
.pwa-enter-active,
.pwa-leave-active {
  transition:
    opacity var(--dur) var(--ease),
    transform var(--dur) var(--ease);
}
.pwa-enter-from,
.pwa-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}
@media (max-width: 1023px) {
  .pwa-update {
    bottom: calc(86px + env(safe-area-inset-bottom));
  }
}
</style>
