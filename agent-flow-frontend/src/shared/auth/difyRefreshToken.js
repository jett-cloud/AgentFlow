const DIFY_API_PREFIX = import.meta.env?.VITE_DIFY_API_PREFIX || '/console/api'

const LOCAL_STORAGE_KEY = 'is_other_tab_refreshing'
const DEFAULT_TIMEOUT_MS = 10000

let isRefreshing = false

function waitUntilTokenRefreshed() {
  return new Promise((resolve) => {
    function check() {
      const sign = globalThis.localStorage?.getItem(LOCAL_STORAGE_KEY)
      if ((sign && sign === '1') || isRefreshing) {
        setTimeout(check, 200)
        return
      }
      resolve()
    }
    check()
  })
}

function isRefreshingSignAvailable(deltaMs) {
  const now = Date.now()
  const last = Number.parseInt(globalThis.localStorage?.getItem('last_refresh_time') || '0', 10)
  return now - last <= deltaMs
}

function releaseRefreshLock() {
  isRefreshing = false
  try {
    globalThis.localStorage?.removeItem(LOCAL_STORAGE_KEY)
    globalThis.localStorage?.removeItem('last_refresh_time')
  }
  catch {
    // ignore storage errors
  }
  globalThis.removeEventListener?.('beforeunload', releaseRefreshLock)
}

async function getNewAccessToken(timeoutMs) {
  try {
    const sign = globalThis.localStorage?.getItem(LOCAL_STORAGE_KEY)
    if ((sign === '1' && isRefreshingSignAvailable(timeoutMs)) || isRefreshing) {
      await waitUntilTokenRefreshed()
      return
    }

    isRefreshing = true
    try {
      globalThis.localStorage?.setItem(LOCAL_STORAGE_KEY, '1')
      globalThis.localStorage?.setItem('last_refresh_time', String(Date.now()))
    }
    catch {
      // ignore storage errors
    }
    globalThis.addEventListener?.('beforeunload', releaseRefreshLock)

    const response = await fetch(`${DIFY_API_PREFIX}/refresh-token`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json;utf-8',
      },
    })
    if (response.status === 401 || !response.ok)
      throw new Error('refresh token failed')
  }
  finally {
    releaseRefreshLock()
  }
}

/**
 * Refresh access/CSRF cookies via Console API. Single-flight across callers/tabs.
 * @param {number} [timeoutMs]
 */
export async function refreshAccessTokenOrReLogin(timeoutMs = DEFAULT_TIMEOUT_MS) {
  return Promise.race([
    new Promise((_, reject) => {
      setTimeout(() => {
        releaseRefreshLock()
        reject(new Error('refresh token timeout'))
      }, timeoutMs)
    }),
    getNewAccessToken(timeoutMs),
  ])
}
