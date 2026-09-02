import test from 'node:test'
import assert from 'node:assert/strict'
import {
  extractInstallTaskId,
  isAuthorizationError,
  waitForPluginInstallTask,
} from './pluginInstallHelpers.js'

test('extracts the generated plugin install task id from the backend response', () => {
  assert.equal(extractInstallTaskId({ task: { task_id: 'task-1' } }), 'task-1')
  assert.equal(extractInstallTaskId({ data: { task: { task_id: 'task-2' } } }), 'task-2')
  assert.equal(extractInstallTaskId({ task_id: 'task-3' }), 'task-3')
  assert.equal(extractInstallTaskId({ task: { all_installed: true } }), '')
})

test('waits for a plugin install task to succeed', async () => {
  const responses = [
    { task: { status: 'running' } },
    { data: { task: { status: 'success' } } },
  ]
  let calls = 0

  const task = await waitForPluginInstallTask(
    async () => responses[calls++],
    'task-1',
    { intervalMs: 0 },
  )

  assert.equal(task.status, 'success')
  assert.equal(calls, 2)
})

test('reports the failed plugin message from an install task', async () => {
  await assert.rejects(
    waitForPluginInstallTask(
      async () => ({
        status: 'failed',
        plugins: [{ status: 'failed', message: 'invalid package' }],
      }),
      'task-1',
      { intervalMs: 0 },
    ),
    /invalid package/,
  )
})

test('times out using the marketplace install polling limit', async () => {
  let calls = 0

  await assert.rejects(
    waitForPluginInstallTask(
      async () => {
        calls += 1
        return { status: 'running' }
      },
      'task-1',
      { maxAttempts: 2, intervalMs: 0 },
    ),
    /插件安装超时/,
  )
  assert.equal(calls, 2)
})

test('recognizes HTTP authorization and credential error messages', () => {
  assert.equal(isAuthorizationError({ response: { status: 403 } }), true)
  assert.equal(isAuthorizationError('Missing credentials for this tool'), true)
  assert.equal(isAuthorizationError('请先配置 API Key 凭证'), true)
  assert.equal(isAuthorizationError('tool execution failed'), false)
})
