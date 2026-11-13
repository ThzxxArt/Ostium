<script setup lang="ts">
import { computed } from 'vue'
import { NModal } from 'naive-ui'
import QrcodeVue from 'qrcode.vue'
import { useI18n } from 'vue-i18n'
import OCopyButton from './OCopyButton.vue'
import { useCopy } from '@/composables/useCopy'

const props = defineProps<{
  show: boolean
  value: string
  title?: string
  description?: string
}>()

const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const visible = computed({
  get: () => props.show,
  set: (value: boolean) => emit('update:show', value),
})

const { copy } = useCopy()
const { t } = useI18n()
</script>

<template>
  <NModal v-model:show="visible" preset="card" style="max-width: 420px" :bordered="false">
    <template #header>{{ title || t('common.scan_to_import') }}</template>
    <div class="qr-wrap">
      <div class="qr">
        <QrcodeVue :value="value" :size="232" level="M" foreground="#0b1220" background="#ffffff" />
      </div>
      <p v-if="description" class="o-muted o-small">{{ description }}</p>
      <div class="link">
        <code class="o-truncate">{{ value }}</code>
        <OCopyButton :value="value" size="tiny" />
      </div>
      <button class="manual" type="button" @click="copy(value)">{{ t('common.copy_link') }}</button>
    </div>
  </NModal>
</template>

<style scoped>
.qr-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}
.qr {
  padding: 14px;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.24);
}
.link {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-2);
}
.link code {
  flex: 1;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.manual {
  border: 0;
  background: transparent;
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
}
</style>
