<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
  eyebrow?: string
}>()
</script>

<template>
  <header class="page-header">
    <div class="copy">
      <p v-if="eyebrow" class="o-kicker">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="o-muted">{{ subtitle }}</p>
    </div>
    <div class="actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}
.copy {
  min-width: 0;
  max-width: 780px;
}
h1 {
  font-size: 24px;
  line-height: 1.3;
  font-weight: 600;
  letter-spacing: -0.02em;
  margin-top: 2px;
}
p {
  margin-top: 6px;
  font-size: 13.5px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
@media (max-width: 767px) {
  .page-header {
    margin-bottom: 18px;
  }
  h1 {
    font-size: 21px;
  }
}
</style>
