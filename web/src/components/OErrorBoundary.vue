<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const failed = ref(false)

onErrorCaptured((error) => {
  console.error('Unhandled UI error', error)
  failed.value = true
  return false
})

function reload() {
  window.location.reload()
}
</script>

<template>
  <div v-if="failed" class="o-card boundary" role="alert">
    <h2>{{ t('errors.boundary_title') }}</h2>
    <p class="o-muted">{{ t('errors.boundary_desc') }}</p>
    <button type="button" class="o-button" @click="reload">{{ t('common.retry') }}</button>
  </div>
  <slot v-else />
</template>

<style scoped>
.boundary {
  margin: 40px auto;
  max-width: 560px;
  padding: 28px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.boundary h2 {
  font-size: 18px;
}
</style>
