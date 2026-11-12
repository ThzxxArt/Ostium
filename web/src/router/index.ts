import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { i18n } from '@/locales'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/pages/LoginPage.vue'),
      meta: { public: true, titleKey: 'auth.login' },
    },
    {
      path: '/setup',
      name: 'setup',
      component: () => import('@/pages/SetupPage.vue'),
      meta: { public: true, titleKey: 'setup.title' },
    },
    {
      path: '/onboarding',
      name: 'onboarding',
      component: () => import('@/pages/OnboardingPage.vue'),
      meta: { requiresAuth: true, role: 'client', titleKey: 'onboarding.title' },
    },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        {
          path: '',
          name: 'home',
          component: () => import('@/pages/HomeGate.vue'),
          meta: { requiresAuth: true, titleKey: 'nav.dashboard' },
        },
        {
          path: 'inbounds',
          name: 'inbounds',
          component: () => import('@/pages/InboundsPage.vue'),
          meta: { requiresAuth: true, role: 'server', titleKey: 'nav.inbounds' },
        },
        {
          path: 'users',
          name: 'users',
          component: () => import('@/pages/UsersPage.vue'),
          meta: { requiresAuth: true, role: 'server', titleKey: 'nav.users' },
        },
        {
          path: 'subscriptions',
          name: 'subscriptions',
          component: () => import('@/pages/SubscriptionsPage.vue'),
          meta: { requiresAuth: true, role: 'server', titleKey: 'nav.subscriptions' },
        },
        {
          path: 'connections',
          name: 'connections',
          component: () => import('@/pages/ConnectionsPage.vue'),
          meta: { requiresAuth: true, role: 'server', titleKey: 'nav.connections' },
        },
        {
          path: 'rules',
          name: 'rules',
          component: () => import('@/pages/RulesPage.vue'),
          meta: { requiresAuth: true, role: 'server', titleKey: 'nav.rules' },
        },
        {
          path: 'certificates',
          name: 'certificates',
          component: () => import('@/pages/CertificatesPage.vue'),
          meta: { requiresAuth: true, role: 'server', titleKey: 'nav.certificates' },
        },
        {
          path: 'logs',
          name: 'logs',
          component: () => import('@/pages/LogsPage.vue'),
          meta: { requiresAuth: true, titleKey: 'nav.logs' },
        },
        {
          path: 'jobs',
          name: 'jobs',
          component: () => import('@/pages/JobsPage.vue'),
          meta: { requiresAuth: true, titleKey: 'nav.jobs' },
        },
        {
          path: 'system',
          name: 'system',
          component: () => import('@/pages/SystemPage.vue'),
          meta: { requiresAuth: true, role: 'server', titleKey: 'nav.system' },
        },
        {
          path: 'audit',
          name: 'audit',
          component: () => import('@/pages/AuditPage.vue'),
          meta: { requiresAuth: true, role: 'server', titleKey: 'nav.audit' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/pages/SettingsPage.vue'),
          meta: { requiresAuth: true, titleKey: 'nav.settings' },
        },
        {
          path: 'profiles',
          name: 'profiles',
          component: () => import('@/pages/ProfilesPage.vue'),
          meta: { requiresAuth: true, role: 'client', titleKey: 'nav.profiles' },
        },
        {
          path: 'routing',
          name: 'routing',
          component: () => import('@/pages/RoutingPage.vue'),
          meta: { requiresAuth: true, role: 'client', titleKey: 'nav.rules' },
        },
        {
          path: 'network',
          name: 'network',
          component: () => import('@/pages/NetworkPage.vue'),
          meta: { requiresAuth: true, role: 'client', titleKey: 'nav.network' },
        },
        {
          path: 'stats',
          name: 'stats',
          component: () => import('@/pages/StatsPage.vue'),
          meta: { requiresAuth: true, role: 'client', titleKey: 'nav.stats' },
        },
        {
          path: 'diagnostics',
          name: 'diagnostics',
          component: () => import('@/pages/DiagnosticsPage.vue'),
          meta: { requiresAuth: true, role: 'client', titleKey: 'nav.diagnostics' },
        },
        {
          path: ':pathMatch(.*)*',
          name: 'not-found',
          component: () => import('@/pages/NotFoundPage.vue'),
          meta: { requiresAuth: true, titleKey: 'common.empty' },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.bootstrap()

  if (!auth.initialized) {
    return to.name === 'setup' ? true : { name: 'setup' }
  }
  if (to.name === 'setup') {
    return auth.authenticated ? { path: '/' } : { name: 'login' }
  }
  if (to.meta.requiresAuth && !auth.authenticated) {
    return { name: 'login', query: { next: to.fullPath } }
  }
  if (to.name === 'login' && auth.authenticated) {
    return { path: '/' }
  }
  if (to.meta.role && auth.role !== to.meta.role) {
    return { path: '/' }
  }
  return true
})

router.afterEach((to) => {
  const { t } = i18n.global
  const auth = useAuthStore()
  const title =
    to.name === 'home'
      ? t(auth.isServer ? 'nav.dashboard' : 'nav.home')
      : to.meta.titleKey
        ? t(String(to.meta.titleKey))
        : t('app.name')
  document.title = title === 'Ostium' ? 'Ostium' : `${title} · Ostium`
})

export default router
