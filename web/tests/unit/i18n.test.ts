import { describe, expect, it } from 'vitest'
import en from '@/locales/en'
import zh from '@/locales/zh'

function flatten(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object') return prefix ? [prefix] : []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    flatten(child, prefix ? `${prefix}.${key}` : key),
  )
}

describe('locale parity', () => {
  it('has identical key sets in Chinese and English', () => {
    const zhKeys = new Set(flatten(zh))
    const enKeys = new Set(flatten(en))
    const missingInEn = [...zhKeys].filter((key) => !enKeys.has(key))
    const missingInZh = [...enKeys].filter((key) => !zhKeys.has(key))
    expect(missingInEn, `missing in en: ${missingInEn.join(', ')}`).toEqual([])
    expect(missingInZh, `missing in zh: ${missingInZh.join(', ')}`).toEqual([])
  })

  it('has no empty strings', () => {
    for (const [name, messages] of [
      ['zh', zh],
      ['en', en],
    ] as const) {
      for (const key of flatten(messages)) {
        const value = key
          .split('.')
          .reduce<unknown>(
            (node, part) => (node as Record<string, unknown> | undefined)?.[part],
            messages,
          )
        expect(String(value).trim(), `${name}.${key}`).not.toBe('')
      }
    }
  })
})
