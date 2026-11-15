import { describe, expect, it } from 'vitest'
import {
  formatBytes,
  formatDuration,
  formatRate,
  formatTime,
  initials,
  percentOf,
  statusTone,
} from '../../src/utils/format'

describe('format utilities', () => {
  it('formats bytes with binary units', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(1024)).toBe('1.0 KiB')
    expect(formatBytes(1536)).toBe('1.5 KiB')
    expect(formatBytes(1024 ** 3)).toBe('1.0 GiB')
  })

  it('formats rates and durations', () => {
    expect(formatRate(2048)).toBe('2.0 KiB/s')
    expect(formatDuration(3661)).toBe('1h 1m')
    expect(formatDuration(90061)).toBe('1d 1h')
  })

  it('computes quota percentages safely', () => {
    expect(percentOf(50, 100)).toBe(50)
    expect(percentOf(200, 100)).toBe(100)
    expect(percentOf(10, 0)).toBe(0)
  })

  it('derives initials', () => {
    expect(initials('alice')).toBe('AL')
    expect(initials('Alice Chen')).toBe('AC')
    expect(initials('')).toBe('?')
  })

  it('maps statuses to tones', () => {
    expect(statusTone('connected')).toBe('success')
    expect(statusTone('warning')).toBe('warning')
    expect(statusTone('failed')).toBe('danger')
    expect(statusTone('disabled')).toBe('neutral')
  })
})

describe('formatTime', () => {
  it('renders a UTC timestamp in the viewer timezone', () => {
    const value = '2026-11-15T00:30:00Z'
    const rendered = formatTime(value, 'en-US')
    const expected = new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date(value))
    expect(rendered).toBe(expected)
    expect(rendered).toContain(':')
  })
})
