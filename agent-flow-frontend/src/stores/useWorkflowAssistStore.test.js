import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkflowAssistStore } from './useWorkflowAssistStore.js'

test('workflow assist dock opens, closes, and toggles', () => {
  setActivePinia(createPinia())
  const store = useWorkflowAssistStore()

  assert.equal(store.panelOpen, false)

  store.open()
  assert.equal(store.panelOpen, true)

  store.toggle()
  assert.equal(store.panelOpen, false)

  store.close()
  assert.equal(store.panelOpen, false)
})

test('preferred tools and datasets persist without duplicates', () => {
  const stored = new Map()
  const originalLocalStorage = globalThis.localStorage
  globalThis.localStorage = {
    getItem: key => stored.get(key) || null,
    setItem: (key, value) => stored.set(key, value),
  }

  try {
    setActivePinia(createPinia())
    const store = useWorkflowAssistStore()

    store.addPreferredTool({ provider_name: 'web', tool_name: 'search', label: '网页搜索' })
    store.addPreferredTool({ provider_name: 'web', tool_name: 'search', label: '网页搜索' })
    store.addPreferredDataset({ id: 'dataset-1', name: '产品知识库' })

    assert.deepEqual(store.preferredTools, [{ provider_name: 'web', tool_name: 'search', label: '网页搜索' }])
    assert.deepEqual(store.preferredDatasets, [{ id: 'dataset-1', name: '产品知识库' }])
    assert.deepEqual(JSON.parse(stored.get('workflow-assist:prefs')), {
      preferredTools: [{ provider_name: 'web', tool_name: 'search', label: '网页搜索' }],
      preferredDatasets: [{ id: 'dataset-1', name: '产品知识库' }],
    })

    store.removePreferredTool({ provider_name: 'web', tool_name: 'search' })
    store.removePreferredDataset('dataset-1')
    assert.deepEqual(store.preferredTools, [])
    assert.deepEqual(store.preferredDatasets, [])
  }
  finally {
    globalThis.localStorage = originalLocalStorage
  }
})

test('active run coordinates persist until a terminal or stop', () => {
  setActivePinia(createPinia())
  const store = useWorkflowAssistStore()

  store.setAppCoordination('app-1', { conversation_id: 'conv-1', run_id: 'run-1', epoch: 2, cursor: 3 })
  assert.deepEqual(store.getAppCoordination('app-1'), {
    conversation_id: 'conv-1',
    run_id: 'run-1',
    epoch: 2,
    cursor: 3,
  })

  store.advanceAppCursor('app-1', 5)
  assert.equal(store.getAppCoordination('app-1').cursor, 5)
  store.advanceAppCursor('app-1', 4)
  assert.equal(store.getAppCoordination('app-1').cursor, 5)

  store.clearAppCoordination('app-1')
  assert.deepEqual(store.getAppCoordination('app-1'), {
    conversation_id: '',
    run_id: '',
    epoch: null,
    cursor: 0,
  })
})

test('execution consent mode defaults to always ask and persists only known values', () => {
  const stored = new Map()
  const originalLocalStorage = globalThis.localStorage
  globalThis.localStorage = {
    getItem: key => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
  }

  try {
    setActivePinia(createPinia())
    const store = useWorkflowAssistStore()
    assert.equal(store.executionConsentMode, 'always_ask')

    store.setExecutionConsentMode('always_execute')
    assert.equal(stored.get('workflow-assist:execution-consent'), 'always_execute')

    setActivePinia(createPinia())
    assert.equal(useWorkflowAssistStore().executionConsentMode, 'always_execute')

    store.setExecutionConsentMode('sometimes')
    assert.equal(store.executionConsentMode, 'always_ask')
  }
  finally {
    globalThis.localStorage = originalLocalStorage
  }
})
