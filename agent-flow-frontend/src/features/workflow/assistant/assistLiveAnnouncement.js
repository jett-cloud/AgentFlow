export function createAssistLiveAnnouncement({
  delay = 250,
  setTimeoutImpl = globalThis.setTimeout?.bind(globalThis),
  clearTimeoutImpl = globalThis.clearTimeout?.bind(globalThis),
  onAnnounce = () => {},
} = {}) {
  let timer = null
  let pending = ''

  function clear() {
    if (timer !== null && clearTimeoutImpl)
      clearTimeoutImpl(timer)
    timer = null
  }

  function update(text) {
    const next = String(text || '').trim()
    if (!next) {
      flush()
      return
    }
    pending = next
    clear()
    if (!setTimeoutImpl)
      return
    const scheduled = setTimeoutImpl(() => {
      if (timer !== scheduled)
        return
      timer = null
      const announcement = pending
      pending = ''
      if (announcement)
        onAnnounce(announcement)
    }, delay)
    timer = scheduled
  }

  function flush() {
    const announcement = pending
    pending = ''
    clear()
    if (announcement)
      onAnnounce(announcement)
  }

  function dispose() {
    clear()
    pending = ''
  }

  return { dispose, flush, update }
}

export function createAssistStatusAnnouncement({ onAnnounce = () => {} } = {}) {
  const lastStatusByChannel = new Map()

  function update(channel, status, text) {
    const nextChannel = String(channel || '')
    const nextStatus = String(status || '')
    const nextText = String(text || '').trim()
    if (!nextChannel || !nextStatus || !nextText || lastStatusByChannel.get(nextChannel) === nextStatus)
      return false
    lastStatusByChannel.set(nextChannel, nextStatus)
    onAnnounce(nextText)
    return true
  }

  function reset(channel) {
    lastStatusByChannel.delete(String(channel || ''))
  }

  function dispose() {
    lastStatusByChannel.clear()
  }

  return { dispose, reset, update }
}
