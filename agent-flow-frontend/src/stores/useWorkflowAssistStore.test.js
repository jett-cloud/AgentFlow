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

  store.setActiveRun('conv-1', { runId: 'run-1', epoch: 2, cursor: 3 })
  assert.deepEqual(store.getActiveRun('conv-1'), { runId: 'run-1', epoch: 2, cursor: 3 })

  store.advanceRunCursor('conv-1', 5)
  assert.equal(store.getActiveRun('conv-1').cursor, 5)
  store.advanceRunCursor('conv-1', 4)
  assert.equal(store.getActiveRun('conv-1').cursor, 5)

  store.clearActiveRun('conv-1')
  assert.equal(store.getActiveRun('conv-1'), null)
})
