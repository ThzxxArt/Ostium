<script setup lang="ts">
import { defineAsyncComponent } from 'vue'
import { useAuthStore } from '@/stores/auth'

const DashboardPage = defineAsyncComponent(() => import('./DashboardPage.vue'))
const ClientHomePage = defineAsyncComponent(() => import('./ClientHomePage.vue'))
const auth = useAuthStore()
</script>

<template>
  <component :is="auth.isServer ? DashboardPage : ClientHomePage" />
</template>
