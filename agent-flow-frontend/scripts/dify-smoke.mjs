/**
 * End-to-end Console API smoke against Vite proxy (same path as the Vue app).
 * Usage: node scripts/dify-smoke.mjs
 */
import { Buffer } from 'node:buffer'

const BASE = process.env.DIFY_SMOKE_BASE || 'http://localhost:5173'
const API = `${BASE}/console/api`
const stamp = Date.now()
const email = `smoke_${stamp}@example.com`
const password = 'Test1234'
const name = `Smoke ${stamp}`

const jar = new Map()

function encodePassword(value) {
  return Buffer.from(value, 'utf8').toString('base64')
}

function storeCookies(res) {
  const raw = typeof res.headers.getSetCookie === 'function'
    ? res.headers.getSetCookie()
    : (res.headers.get('set-cookie') ? [res.headers.get('set-cookie')] : [])
  for (const line of raw) {
    const pair = line.split(';')[0]
    const eq = pair.indexOf('=')
    if (eq <= 0)
      continue
    const key = pair.slice(0, eq)
    const value = pair.slice(eq + 1)
    jar.set(key, value)
  }
}

function cookieHeader() {
  return [...jar.entries()].map(([k, v]) => `${k}=${v}`).join('; ')
}

function csrfToken() {
  return jar.get('__Host-csrf_token') || jar.get('csrf_token') || ''
}

async function api(method, path, body, { silent404 = false } = {}) {
  const headers = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  }
  const cookie = cookieHeader()
  if (cookie)
    headers.Cookie = cookie
  const csrf = csrfToken()
  if (csrf)
    headers['X-CSRF-Token'] = csrf

  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  storeCookies(res)
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { raw: text.slice(0, 300) }
  }
  if (!res.ok) {
    if (silent404 && res.status === 404)
      return { ok: false, status: res.status, data }
    const err = new Error(`${method} ${path} -> ${res.status} ${data?.message || data?.code || text.slice(0, 200)}`)
    err.status = res.status
    err.data = data
    throw err
  }
  return { ok: true, status: res.status, data }
}

function step(title) {
  console.log(`\n== ${title}`)
}

function ok(msg, extra) {
  console.log(`  OK  ${msg}${extra !== undefined ? ` ${JSON.stringify(extra)}` : ''}`)
}

function minimalGraph() {
  const startId = 'start'
  const endId = 'end'
  return {
    nodes: [
      {
        id: startId,
        type: 'custom',
        position: { x: 80, y: 200 },
        data: { type: 'start', title: '开始', variables: [], desc: '' },
        sourcePosition: 'right',
        targetPosition: 'left',
      },
      {
        id: endId,
        type: 'custom',
        position: { x: 420, y: 200 },
        data: {
          type: 'end',
          title: '结束',
          outputs: [],
          desc: '',
        },
        sourcePosition: 'right',
        targetPosition: 'left',
      },
    ],
    edges: [
      {
        id: `${startId}-${endId}`,
        type: 'custom',
        source: startId,
        target: endId,
        sourceHandle: 'source',
        targetHandle: 'target',
        data: { sourceType: 'start', targetType: 'end' },
      },
    ],
    viewport: { x: 0, y: 0, zoom: 1 },
  }
}

async function main() {
  const report = []

  step('1. setup')
  const setup = await api('GET', '/setup')
  ok('setup', setup.data)
  report.push(['setup', setup.data.step])

  step('2. register (/dev-register)')
  const reg = await api('POST', '/dev-register', {
    email,
    name,
    password: encodePassword(password),
    language: 'zh-Hans',
    timezone: 'Asia/Shanghai',
  })
  ok('register', reg.data)
  report.push(['register', reg.data.result, `cookies=${jar.size}`])

  step('3. profile (CSRF on GET)')
  const profile = await api('GET', '/account/profile')
  ok('profile', { email: profile.data.email, name: profile.data.name })
  report.push(['profile', profile.data.email])

  step('4. create workflow app')
  const app = await api('POST', '/apps', {
    name: `联调 ${stamp}`,
    mode: 'workflow',
    description: 'smoke',
    icon_type: 'emoji',
    icon: '🤖',
    icon_background: '#FFEAD5',
  })
  const appId = app.data.id
  ok('create app', { id: appId })
  report.push(['createApp', appId])

  step('5. draft missing -> ensure')
  let draftHash = null
  const missing = await api('GET', `/apps/${appId}/workflows/draft`, undefined, { silent404: true })
  if (missing.ok) {
    draftHash = missing.data.hash
    ok('draft already exists', { hash: draftHash })
  } else {
    ok('draft missing as expected', { code: missing.data?.code })
    const init = await api('POST', `/apps/${appId}/workflows/draft`, {
      graph: { nodes: [], edges: [] },
      features: { retriever_resource: { enabled: true } },
      environment_variables: [],
      conversation_variables: [],
    })
    draftHash = init.data.hash
    ok('init empty draft', init.data)
  }

  step('6. save graph (start -> end)')
  const graph = minimalGraph()
  const saved = await api('POST', `/apps/${appId}/workflows/draft`, {
    graph,
    features: { retriever_resource: { enabled: true } },
    environment_variables: [],
    conversation_variables: [],
    hash: draftHash,
  })
  ok('save draft', saved.data)
  const hash = saved.data.hash
  report.push(['saveDraft', hash])

  step('7. reload draft')
  const draft = await api('GET', `/apps/${appId}/workflows/draft`)
  const nodeTypes = (draft.data.graph?.nodes || []).map(n => n.data?.type || n.type)
  ok('reload draft', { hash: draft.data.hash, nodes: nodeTypes })
  if (draft.data.hash !== hash)
    throw new Error(`hash mismatch after reload: ${draft.data.hash} vs ${hash}`)
  report.push(['reloadDraft', nodeTypes.join(',')])

  step('8. list apps')
  const list = await api('GET', '/apps?page=1&limit=30&mode=workflow')
  const found = (list.data.data || []).some(item => item.id === appId)
  ok('list contains app', { found, total: list.data.total ?? (list.data.data || []).length })
  report.push(['listApps', found])

  step('9. run draft (SSE, 20s timeout)')
  const runHeaders = {
    Accept: 'text/event-stream',
    'Content-Type': 'application/json',
    Cookie: cookieHeader(),
    'X-CSRF-Token': csrfToken(),
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 20000)
  let runText = ''
  let runStatus = 0
  try {
    const runRes = await fetch(`${API}/apps/${appId}/workflows/draft/run`, {
      method: 'POST',
      headers: runHeaders,
      body: JSON.stringify({ inputs: {}, files: [] }),
      signal: controller.signal,
    })
    storeCookies(runRes)
    runStatus = runRes.status
    if (!runRes.ok) {
      runText = await runRes.text()
      console.log(`  WARN run failed ${runStatus}: ${runText.slice(0, 400)}`)
      report.push(['runDraft', `FAIL ${runStatus}`])
    } else if (!runRes.body) {
      runText = await runRes.text()
      report.push(['runDraft', 'NO_BODY'])
    } else {
      const reader = runRes.body.getReader()
      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done)
          break
        runText += decoder.decode(value, { stream: true })
        if (/workflow_finished|error/.test(runText)) {
          try { await reader.cancel() } catch { /* ignore */ }
          break
        }
      }
      const events = [...runText.matchAll(/"event"\s*:\s*"([^"]+)"/g)].map(m => m[1])
      ok('run draft', { status: runStatus, events: events.slice(0, 12) })
      report.push(['runDraft', events.join('|') || `bytes=${runText.length}`])
      const taskMatch = runText.match(/"task_id"\s*:\s*"([^"]+)"/)
      if (taskMatch && !events.includes('workflow_finished')) {
        step('10. stop run')
        try {
          const stop = await api('POST', `/apps/${appId}/workflow-runs/tasks/${taskMatch[1]}/stop`, {})
          ok('stop', stop.data)
          report.push(['stopRun', stop.data?.result || stop.status])
        } catch (error) {
          console.log(`  WARN stop: ${error.message}`)
          report.push(['stopRun', `WARN ${error.message}`])
        }
      }
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      const events = [...runText.matchAll(/"event"\s*:\s*"([^"]+)"/g)].map(m => m[1])
      console.log(`  WARN run timed out; partial events=${events.join('|') || '(none)'} bytes=${runText.length}`)
      report.push(['runDraft', `TIMEOUT events=${events.join('|') || 'none'}`])
    } else {
      console.log(`  WARN run error: ${error.message}`)
      report.push(['runDraft', `WARN ${error.message}`])
    }
  } finally {
    clearTimeout(timer)
  }

  step('11. login again')
  jar.clear()
  const login = await api('POST', '/login', {
    email,
    password: encodePassword(password),
    language: 'zh-Hans',
    remember_me: true,
  })
  ok('login', login.data)
  const profile2 = await api('GET', '/account/profile')
  ok('profile after login', { email: profile2.data.email })
  const draft2 = await api('GET', `/apps/${appId}/workflows/draft`)
  ok('draft persists after re-login', { hash: draft2.data.hash, nodes: draft2.data.graph?.nodes?.length })
  report.push(['reloginPersist', draft2.data.hash === hash])

  console.log('\n======== SMOKE SUMMARY ========')
  for (const row of report)
    console.log(`- ${row[0]}: ${row.slice(1).join(' | ')}`)
  console.log(`\nappId=${appId}`)
  console.log(`email=${email} password=${password}`)
}

main().catch((error) => {
  console.error('\nSMOKE FAILED:', error.message)
  if (error.data)
    console.error(JSON.stringify(error.data, null, 2))
  process.exit(1)
})
