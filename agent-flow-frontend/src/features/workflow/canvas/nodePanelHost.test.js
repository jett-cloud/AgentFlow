import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const hostLogicUrl = new URL('./nodePanelHost.js', import.meta.url)

test('panel width preserves at least 400px of usable desktop canvas', async () => {
  assert.equal(existsSync(hostLogicUrl), true)
  const { clampNodePanelWidth } = await import(hostLogicUrl)
  assert.equal(clampNodePanelWidth(900, 1844), 850)
  assert.equal(clampNodePanelWidth(900, 960), 560)
  assert.equal(clampNodePanelWidth(200, 960), 400)
})

test('last-run tab only exists for nodes supporting single run', async () => {
  assert.equal(existsSync(hostLogicUrl), true)
  const { getNodePanelTabs } = await import(hostLogicUrl)
  assert.deepEqual(getNodePanelTabs(false), ['settings'])
  assert.deepEqual(getNodePanelTabs(true), ['settings', 'last-run'])
})

test('opening the same node id refreshes a replaced start-placeholder snapshot', async () => {
  const { openNodePanelState } = await import(hostLogicUrl)
  const activeNodeId = { value: 'start-1' }
  const activeNode = {
    value: {
      id: 'start-1',
      type: 'start-placeholder',
      data: { type: 'start-placeholder', title: '选择开始节点' },
    },
  }
  const liveNode = {
    id: 'start-1',
    type: 'start',
    data: { type: 'start', title: '开始', variables: [] },
    position: { x: 100, y: 120 },
  }

  openNodePanelState({
    nodeId: 'start-1',
    findNode: id => id === liveNode.id ? liveNode : undefined,
    activeNodeId,
    activeNode,
  })

  assert.equal(activeNodeId.value, 'start-1')
  assert.deepEqual(activeNode.value, {
    id: 'start-1',
    type: 'start',
    data: { type: 'start', title: '开始', variables: [] },
    parentNode: undefined,
    parentId: undefined,
  })
})

test('WorkflowCanvas delegates panel presentation to a controlled NodePanelHost', () => {
  const hostUrl = new URL('./components/NodePanelHost.vue', import.meta.url)
  assert.equal(existsSync(hostUrl), true)
  const canvas = readFileSync(new URL('./WorkflowCanvas.vue', import.meta.url), 'utf8')
  const host = readFileSync(hostUrl, 'utf8')

  assert.match(canvas, /<NodePanelHost/)
  assert.doesNotMatch(canvas, /class="node-panel-tabs"/)
  assert.doesNotMatch(canvas, /class="resize-handle"/)
  assert.match(host, /PanelHeader/)
  assert.match(host, /LastRunPanel/)
  assert.match(host, /update:activeTab/)
  assert.match(host, /update:width/)
})

test('last-run form fields cannot overflow the panel width', () => {
  const source = readFileSync(new URL('../nodes/shared/LastRunPanel.vue', import.meta.url), 'utf8')
  assert.match(source, /\.field textarea \{[\s\S]*box-sizing:\s*border-box/)
})
