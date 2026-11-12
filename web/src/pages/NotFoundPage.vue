<script setup lang="ts">
import { NButton } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Compass } from '@lucide/vue'

const router = useRouter()
const { t } = useI18n()
</script>

<template>
  <div class="o-page not-found">
    <div class="art">
      <span class="ring a" />
      <span class="ring b" />
      <Compass :size="42" :stroke-width="1.3" />
    </div>
    <p class="o-kicker">404</p>
    <h1>{{ t('common.empty') }}</h1>
    <p class="o-muted">{{ t('errors.not_found') }}</p>
    <NButton type="primary" @click="router.push('/')">
      <template #icon><ArrowLeft :size="16" /></template>
      {{ t('common.back') }}
    </NButton>
  </div>
</template>

<style scoped>
.not-found {
  min-height: 60vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 8px;
}
.art {
  position: relative;
  width: 120px;
  height: 120px;
  display: grid;
  place-items: center;
  color: var(--accent);
  margin-bottom: 8px;
}
.ring {
  position: absolute;
  border-radius: 50%;
  border: 1px solid color-mix(in srgb, var(--accent) 24%, transparent);
}
.ring.a {
  inset: 0;
}
.ring.b {
  inset: 18px;
  border-style: dashed;
}
h1 {
  font-size: 26px;
  letter-spacing: -0.03em;
}
p {
  max-width: 420px;
  margin-bottom: 12px;
}
</style>
