import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { EventFrame } from '@/api/types'

export const useEventStore = defineStore('events', () => {
  const connected = ref(false)
  const frames = ref<EventFrame[]>([])
  const lastLog = ref<EventFrame | null>(null)
  const lastJob = ref<EventFrame | null>(null)
  const lastAlert = ref<EventFrame | null>(null)
  const lastEngine = ref<EventFrame | null>(null)
  let socket: WebSocket | null = null
  let retry = 0
  let timer: number | null = null
  let stopped = true

  function handle(frame: EventFrame) {
    frames.value.push(frame)
    if (frames.value.length > 200) frames.value.shift()
    if (frame.type === 'log') lastLog.value = frame
    if (frame.type === 'job.updated' || frame.type === 'job.created') lastJob.value = frame
    if (frame.type === 'alert.created') lastAlert.value = frame
    if (frame.type === 'engine.applied' || frame.type === 'stats.tick') lastEngine.value = frame
  }

  function connect() {
    if (socket) return
    stopped = false
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/api/v1/events`
    try {
      socket = new WebSocket(url)
    } catch {
      schedule()
      return
    }
    socket.addEventListener('open', () => {
      connected.value = true
      retry = 0
    })
    socket.addEventListener('message', (event) => {
      try {
        const frame = JSON.parse(event.data) as EventFrame
        if (frame.type !== 'ping') handle(frame)
      } catch {
        /* ignore malformed frames */
      }
    })
    socket.addEventListener('close', () => {
      connected.value = false
      socket = null
      if (!stopped) schedule()
    })
    socket.addEventListener('error', () => {
      socket?.close()
    })
  }

  function schedule() {
    if (timer !== null) return
    const delay = Math.min(30_000, 1000 * 2 ** retry)
    retry += 1
    timer = window.setTimeout(() => {
      timer = null
      if (!stopped) connect()
    }, delay)
  }

  function disconnect() {
    stopped = true
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    socket?.close()
    socket = null
    connected.value = false
  }

  return { connected, frames, lastLog, lastJob, lastAlert, lastEngine, connect, disconnect }
})
