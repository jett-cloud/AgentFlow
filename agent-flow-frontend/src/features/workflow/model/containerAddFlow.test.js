import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const addBlock = readFileSync(new URL('../nodes/iteration/AddBlock.vue', import.meta.url), 'utf8')
const nextStep = readFileSync(new URL('../nodes/shared/NextStep.vue', import.meta.url), 'utf8')
const canvas = readFileSync(new URL('../canvas/WorkflowCanvas.vue', import.meta.url), 'utf8')

test('empty container add action follows Dify start-node alignment', () => {
  assert.match(addBlock, /position:\s*absolute/)
  assert.match(addBlock, /top:\s*28px/)
  assert.match(addBlock, /left:\s*56px/)
  assert.match(addBlock, /width:\s*64px/)
  assert.match(addBlock, /margin-left:\s*64px/)
})

test('block selector stays inside the canvas area left of an open node panel', async () => {
  const moduleUrl = new URL('./blockSelectorPosition.js', import.meta.url)
  assert.equal(existsSync(moduleUrl), true)
  const { getBlockSelectorMenuStyle } = await import(moduleUrl)
  assert.deepEqual(getBlockSelectorMenuStyle({ x: 760, y: 300 }), {
    left: 'clamp(8px, 760px, calc(100% - var(--canvas-panel-offset, 14px) - 328px))',
    top: 'clamp(8px, 300px, calc(100% - 460px))',
  })
})

test('panel next-step requests source-relative placement', () => {
  assert.match(nextStep, /preferSourcePosition:\s*true/)
  assert.match(nextStep, /clientX:/)
  assert.match(nextStep, /clientY:/)
  assert.match(canvas, /pendingPreferSourcePosition/)
  assert.match(canvas, /preferSourcePosition/)
})

test('connected nodes are placed after the full source width', async () => {
  const moduleUrl = new URL('./connectedNodePlacement.js', import.meta.url)
  assert.equal(existsSync(moduleUrl), true)
  const { getConnectedNodePosition } = await import(moduleUrl)
  assert.deepEqual(getConnectedNodePosition({
    position: { x: 100, y: 80 },
    dimensions: { width: 240, height: 100 },
  }), { x: 420, y: 80 })

  assert.deepEqual(getConnectedNodePosition({
    position: { x: 100, y: 80 },
    style: { width: '640px', height: '340px' },
  }), { x: 820, y: 80 })

  assert.deepEqual(getConnectedNodePosition({
    position: { x: 100, y: 80 },
    dimensions: { width: 240, height: 100 },
  }, {
    position: { x: 300, y: 200 },
  }), { x: 720, y: 280 })
})

test('predecessor nodes are placed before the target in absolute flow space', async () => {
  const { getPredecessorNodePosition } = await import('./connectedNodePlacement.js')

  assert.deepEqual(getPredecessorNodePosition({
    position: { x: 500, y: 80 },
  }), { x: 180, y: 80 })

  assert.deepEqual(getPredecessorNodePosition({
    position: { x: 300, y: 80 },
  }, {
    position: { x: 400, y: 200 },
  }), { x: 380, y: 280 })
})

test('a connected container child does not also connect to the container start', async () => {
  const moduleUrl = new URL('./containerChildConnection.js', import.meta.url)
  assert.equal(existsSync(moduleUrl), true)
  const { shouldConnectContainerStart } = await import(moduleUrl)

  assert.equal(shouldConnectContainerStart({
    parentId: 'loop-1',
    startId: 'loop-1-start',
  }), true)
  assert.equal(shouldConnectContainerStart({
    parentId: 'loop-1',
    startId: 'loop-1-start',
    connectionSourceId: 'child-1',
  }), false)
})
