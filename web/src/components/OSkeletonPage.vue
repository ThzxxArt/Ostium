<script setup lang="ts">
withDefaults(defineProps<{ cards?: number; rows?: number }>(), { cards: 4, rows: 3 })
</script>

<template>
  <div class="skeleton-page" aria-busy="true" aria-label="Loading">
    <div class="header">
      <div class="bar w-40" />
      <div class="bar w-65" />
    </div>
    <div class="cards">
      <div v-for="index in cards" :key="index" class="card">
        <div class="bar w-45" />
        <div class="bar w-70 tall" />
        <div class="bar w-35" />
      </div>
    </div>
    <div class="block">
      <div v-for="index in rows" :key="index" class="row">
        <div class="dot" />
        <div class="bar grow" />
        <div class="bar w-20" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.skeleton-page {
  display: flex;
  flex-direction: column;
  gap: 22px;
}
.header {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}
.card,
.block {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  padding: 18px;
}
.card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 116px;
}
.block {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
}
.bar {
  height: 10px;
  border-radius: 6px;
}
.tall {
  height: 26px;
}
.bar,
.dot {
  background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2));
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite linear;
}
.w-20 {
  width: 20%;
}
.w-35 {
  width: 35%;
}
.w-40 {
  width: 40%;
}
.w-45 {
  width: 45%;
}
.w-65 {
  width: 65%;
}
.w-70 {
  width: 70%;
}
.grow {
  flex: 1;
}
@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}
</style>
