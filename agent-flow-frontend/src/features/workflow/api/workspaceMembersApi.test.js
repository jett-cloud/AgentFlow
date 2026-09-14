import assert from 'node:assert/strict'
import test from 'node:test'
import { fetchWorkspaceMembers, normalizeWorkspaceMembers } from './workspaceMembersApi.js'

test('workspace members API requests /workspaces/current/members', async () => {
  let called
  const client = {
    get(path, config) {
      called = { path, config }
      return { accounts: [{ id: 'a1', name: 'Ada', email: 'ada@example.com' }] }
    },
  }

  const members = await fetchWorkspaceMembers({ language: 'zh-Hans', signal: 'abort-signal', client })

  assert.equal(called.path, '/workspaces/current/members')
  assert.deepEqual(called.config, { params: { language: 'zh-Hans' }, signal: 'abort-signal' })
  assert.deepEqual(members, [{ id: 'a1', name: 'Ada', email: 'ada@example.com' }])
})

test('workspace members responses normalize accounts, data, or arrays', () => {
  const member = { id: 'a1', name: 'Ada', email: 'ada@example.com' }
  assert.deepEqual(normalizeWorkspaceMembers({ accounts: [member] }), [member])
  assert.deepEqual(normalizeWorkspaceMembers({ data: [member] }), [member])
  assert.deepEqual(normalizeWorkspaceMembers([member]), [member])
  assert.deepEqual(normalizeWorkspaceMembers({ accounts: null }), [])
  assert.deepEqual(normalizeWorkspaceMembers({}), [])
})
