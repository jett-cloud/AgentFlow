import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getCsrfToken } from './difyProtocol.js'
import { refreshAccessTokenOrReLogin } from '../auth/difyRefreshToken.js'

export { getCookie, getCsrfToken, isWriteMethod } from './difyProtocol.js'

export const DIFY_API_PREFIX = import.meta.env?.VITE_DIFY_API_PREFIX || '/console/api'
export const CSRF_HEADER_NAME = 'X-CSRF-Token'

const difyClient = axios.create({
  baseURL: DIFY_API_PREFIX,
  timeout: 100000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

difyClient.interceptors.request.use((config) => {
  // Dify validates CSRF on every authenticated Console request (including GET profile).
  const csrfToken = getCsrfToken(document.cookie)
  if (csrfToken)
    config.headers.set(CSRF_HEADER_NAME, csrfToken)
  return config
})

function extractErrorMessage(error) {
  const status = error.response?.status
  const data = error.response?.data
  if (typeof data === 'string') {
    const trimmed = data.trim()
    if (trimmed.startsWith('<!DOCTYPE') || trimmed.startsWith('<!doctype') || trimmed.startsWith('<html')) {
      const url = error.config?.baseURL
        ? `${error.config.baseURL}${error.config.url || ''}`
        : (error.config?.url || '')
      return status === 404
        ? `接口不存在 (404)：${url}`
        : `服务返回了非 JSON 响应 (${status || 'error'})：${url}`
    }
    if (trimmed)
      return trimmed.slice(0, 200)
  }
  return data?.message || data?.error || error.message || 'Dify 服务连接失败'
}

function redirectToLogin() {
  if (window.location.hash === '#/login')
    return
  const current = window.location.hash.replace('#', '') || '/'
  window.location.hash = `#/login?redirect=${encodeURIComponent(current)}`
}

difyClient.interceptors.response.use(
  response => response.data,
  async (error) => {
    if (axios.isCancel(error))
      return Promise.reject(error)

    const status = error.response?.status
    const config = error.config || {}
    const message = extractErrorMessage(error)
    error.message = message

    const canRefresh = status === 401
      && !config.skipAuthRedirect
      && !config._retry
      && !config.skipRefresh

    if (canRefresh) {
      try {
        await refreshAccessTokenOrReLogin()
        config._retry = true
        const csrfToken = getCsrfToken(document.cookie)
        if (csrfToken) {
          if (typeof config.headers?.set === 'function')
            config.headers.set(CSRF_HEADER_NAME, csrfToken)
          else
            config.headers = { ...config.headers, [CSRF_HEADER_NAME]: csrfToken }
        }
        return difyClient.request(config)
      }
      catch {
        redirectToLogin()
      }
    }
    else if (status === 401 && !config.skipAuthRedirect) {
      redirectToLogin()
    }

    if (!config.silent)
      ElMessage.error(message)
    return Promise.reject(error)
  },
)

export default difyClient
