import {
  Activity,
  BarChart3,
  Cable,
  CircleUserRound,
  FileClock,
  Gauge,
  Home,
  LayoutDashboard,
  Link2,
  ListChecks,
  ScrollText,
  ServerCog,
  Settings,
  ShieldCheck,
  Shuffle,
  Stethoscope,
  Users,
  Waypoints,
  Wifi,
} from 'lucide-vue-next'
import type { Component } from 'vue'

export interface NavItem {
  key: string
  path: string
  labelKey: string
  icon: Component
  keywords?: string[]
  badge?: string
}

export interface NavGroup {
  key: string
  labelKey: string
  items: NavItem[]
}

export const serverNav: NavGroup[] = [
  {
    key: 'overview',
    labelKey: 'nav.group_manage',
    items: [
      {
        key: 'dashboard',
        path: '/',
        labelKey: 'nav.dashboard',
        icon: LayoutDashboard,
        keywords: ['overview', 'home'],
      },
      {
        key: 'inbounds',
        path: '/inbounds',
        labelKey: 'nav.inbounds',
        icon: Waypoints,
        keywords: ['reality', 'hysteria2', 'trojan', 'ss2022'],
      },
      {
        key: 'users',
        path: '/users',
        labelKey: 'nav.users',
        icon: Users,
        keywords: ['people', 'quota'],
      },
      {
        key: 'subscriptions',
        path: '/subscriptions',
        labelKey: 'nav.subscriptions',
        icon: Link2,
        keywords: ['sub', 'share', 'qr'],
      },
    ],
  },
  {
    key: 'network',
    labelKey: 'nav.group_network',
    items: [
      {
        key: 'connections',
        path: '/connections',
        labelKey: 'nav.connections',
        icon: Cable,
        keywords: ['sessions'],
      },
      {
        key: 'rules',
        path: '/rules',
        labelKey: 'nav.rules',
        icon: Shuffle,
        keywords: ['routing', 'rules', 'dns'],
      },
      {
        key: 'certificates',
        path: '/certificates',
        labelKey: 'nav.certificates',
        icon: ShieldCheck,
        keywords: ['tls', 'acme'],
      },
    ],
  },
  {
    key: 'observe',
    labelKey: 'nav.group_observe',
    items: [
      { key: 'logs', path: '/logs', labelKey: 'nav.logs', icon: ScrollText, keywords: ['tail'] },
      {
        key: 'jobs',
        path: '/jobs',
        labelKey: 'nav.jobs',
        icon: ListChecks,
        keywords: ['tasks', 'progress'],
      },
      {
        key: 'audit',
        path: '/audit',
        labelKey: 'nav.audit',
        icon: FileClock,
        keywords: ['security', 'history'],
      },
    ],
  },
  {
    key: 'system',
    labelKey: 'nav.group_system',
    items: [
      {
        key: 'system',
        path: '/system',
        labelKey: 'nav.system',
        icon: ServerCog,
        keywords: ['doctor', 'diagnostics'],
      },
      {
        key: 'settings',
        path: '/settings',
        labelKey: 'nav.settings',
        icon: Settings,
        keywords: ['preferences', 'security'],
      },
    ],
  },
]

export const clientNav: NavGroup[] = [
  {
    key: 'connect',
    labelKey: 'nav.group_network',
    items: [
      { key: 'home', path: '/', labelKey: 'nav.home', icon: Home, keywords: ['connect', 'status'] },
      {
        key: 'profiles',
        path: '/profiles',
        labelKey: 'nav.profiles',
        icon: CircleUserRound,
        keywords: ['subscription', 'import'],
      },
      {
        key: 'routing',
        path: '/routing',
        labelKey: 'nav.rules',
        icon: Shuffle,
        keywords: ['rules', 'proxy'],
      },
      {
        key: 'network',
        path: '/network',
        labelKey: 'nav.network',
        icon: Wifi,
        keywords: ['tun', 'system proxy', 'mixed'],
      },
    ],
  },
  {
    key: 'observe',
    labelKey: 'nav.group_observe',
    items: [
      {
        key: 'stats',
        path: '/stats',
        labelKey: 'nav.stats',
        icon: BarChart3,
        keywords: ['traffic'],
      },
      {
        key: 'diagnostics',
        path: '/diagnostics',
        labelKey: 'nav.diagnostics',
        icon: Stethoscope,
        keywords: ['doctor'],
      },
      { key: 'logs', path: '/logs', labelKey: 'nav.logs', icon: ScrollText, keywords: ['tail'] },
    ],
  },
  {
    key: 'system',
    labelKey: 'nav.group_system',
    items: [
      { key: 'jobs', path: '/jobs', labelKey: 'nav.jobs', icon: ListChecks, keywords: ['tasks'] },
      {
        key: 'settings',
        path: '/settings',
        labelKey: 'nav.settings',
        icon: Settings,
        keywords: ['preferences'],
      },
    ],
  },
]

export const clientQuickNav: NavItem[] = [
  clientNav[0].items[0],
  clientNav[0].items[1],
  clientNav[0].items[2],
  clientNav[0].items[3],
]

export const actionIcons = { Activity, Gauge }
