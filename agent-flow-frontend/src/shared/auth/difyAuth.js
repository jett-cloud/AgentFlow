import difyClient from '../http/difyClient.js'
import { encodeSensitiveField } from '../http/difyProtocol.js'

export { encodeSensitiveField } from '../http/difyProtocol.js'

export function loginWithDify(email, password, rememberMe = true) {
  return difyClient.post('/login', {
    email: email.trim().toLowerCase(),
    password: encodeSensitiveField(password),
    language: 'zh-Hans',
    remember_me: rememberMe,
  }, {
    skipAuthRedirect: true,
  })
}

/** Self-service register: creates account + personal workspace, sets Cookie/CSRF. */
export function registerWithDify({ email, name, password }) {
  return difyClient.post('/register', {
    email: email.trim().toLowerCase(),
    name: name.trim(),
    password: encodeSensitiveField(password),
    language: 'zh-Hans',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  }, {
    skipAuthRedirect: true,
  })
}

/** @deprecated use registerWithDify */
export const registerDevelopmentUser = registerWithDify

export function logoutFromDify() {
  return difyClient.post('/logout')
}

export function getDifyProfile(options = {}) {
  return difyClient.get('/account/profile', {
    silent: options.silent ?? true,
    skipAuthRedirect: options.skipAuthRedirect ?? false,
  })
}
