import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { buildServiceWorker } from '../../pwa'

const directories: string[] = []

async function fixture(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'ostium-pwa-'))
  directories.push(directory)
  await mkdir(join(directory, 'assets'), { recursive: true })
  await writeFile(join(directory, 'index.html'), '<div>one</div>')
  await writeFile(join(directory, 'assets', 'app-abc.js'), 'console.log(1)')
  await writeFile(join(directory, 'manifest.webmanifest'), '{"name":"Ostium"}')
  return directory
}

afterEach(async () => {
  await Promise.all(directories.splice(0).map((directory) => rm(directory, { recursive: true })))
})

describe('PWA generator', () => {
  it('uses the same default theme as the application store', async () => {
    const source = await readFile(
      join(import.meta.dirname, '..', '..', 'public', 'theme-init.js'),
      'utf-8',
    )
    expect(source).toContain("localStorage.getItem('ostium.theme') || 'dark'")
  })

  it('hashes asset contents, not just stable filenames', async () => {
    const directory = await fixture()
    const first = await buildServiceWorker(directory)
    expect(first.files).toContain('index.html')
    expect(first.source).toContain('response.ok')
    expect(first.source).toContain("url.pathname.startsWith('/api/')")
    expect(first.source).toContain("url.pathname.startsWith('/sub/')")

    await writeFile(join(directory, 'index.html'), '<div>two</div>')
    const second = await buildServiceWorker(directory)
    expect(second.digest).not.toBe(first.digest)
    expect(second.source).not.toBe(first.source)
  })
})
