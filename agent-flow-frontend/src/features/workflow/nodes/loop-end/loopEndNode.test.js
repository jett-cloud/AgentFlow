import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { BlockEnum } from '../../model/constants.js'
import { canRunBySingle } from '../../model/canRunBySingle.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import {
  CONTAINER_SELECTABLE_BLOCKS,
  SELECTABLE_BLOCKS,
  canConnectAsSource,
  canConnectAsTarget,
} from '../../model/nodeMeta.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodePresentation } from '../../model/nodePresentation.js'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import {
  LOOP_END_DEFAULTS,
  canAddLoopEnd,
  canPasteLoopEnd,
  getLoopEndValidationErrors,
  normalizeLoopEndNodeData,
} from './loopEndNode.js'

const loop = {
  id: 'loop-1',
  type: BlockEnum.Loop,
  data: { type: BlockEnum.Loop },
}

test('uses the official empty defaults and preserves unknown DSL fields', () => {
  assert.deepEqual(LOOP_END_DEFAULTS, {})
  assert.deepEqual(normalizeLoopEndNodeData({
    type: BlockEnum.LoopEnd,
    title: '退出循环',
    future_field: { enabled: true },
  }), {
    type: BlockEnum.LoopEnd,
    title: '退出循环',
    future_field: { enabled: true },
  })
})

test('allows one loop-end only inside a loop container', () => {
  assert.equal(canAddLoopEnd({ nodes: [loop], parentId: loop.id }), true)
  assert.equal(canAddLoopEnd({ nodes: [loop], parentId: null }), false)
  assert.equal(canAddLoopEnd({
    nodes: [
      { id: 'iteration-1', data: { type: BlockEnum.Iteration } },
    ],
    parentId: 'iteration-1',
  }), false)
  assert.equal(canAddLoopEnd({
    nodes: [
      loop,
      { id: 'exit-1', parentNode: loop.id, data: { type: BlockEnum.LoopEnd } },
    ],
    parentId: loop.id,
  }), false)
})

test('only pastes loop-end together with its loop container', () => {
  const exit = {
    id: 'exit-1',
    parentId: loop.id,
    data: { type: BlockEnum.LoopEnd },
  }
  assert.equal(canPasteLoopEnd(exit, [exit]), false)
  assert.equal(canPasteLoopEnd(exit, [loop, exit]), true)
})

test('reports an orphan or duplicate loop-end', () => {
  const orphan = { id: 'orphan', data: { type: BlockEnum.LoopEnd } }
  assert.deepEqual(getLoopEndValidationErrors(orphan, [orphan]), [
    '退出循环节点必须位于循环容器内',
  ])

  const first = { id: 'exit-1', parentNode: loop.id, data: { type: BlockEnum.LoopEnd } }
  const second = { id: 'exit-2', parentNode: loop.id, data: { type: BlockEnum.LoopEnd } }
  assert.deepEqual(getLoopEndValidationErrors(second, [loop, first, second]), [
    '同一循环容器只能有一个退出循环节点',
  ])
})

test('registers loop-end as a loop-only terminal block', () => {
  const { newNode } = generateNewNode({
    type: BlockEnum.LoopEnd,
    id: 'exit-1',
    position: { x: 200, y: 100 },
  })

  assert.equal(newNode.data.title, '退出循环')
  assert.deepEqual(newNode.data, { type: BlockEnum.LoopEnd, title: '退出循环' })
  assert.equal(SELECTABLE_BLOCKS.includes(BlockEnum.LoopEnd), false)
  assert.equal(CONTAINER_SELECTABLE_BLOCKS.includes(BlockEnum.LoopEnd), true)
  assert.equal(canConnectAsTarget(BlockEnum.LoopEnd), true)
  assert.equal(canConnectAsSource(BlockEnum.LoopEnd), false)
  assert.equal(canRunBySingle(BlockEnum.LoopEnd), false)
  assert.deepEqual(getNodeOutputBranches(newNode.data), [])
  assert.deepEqual(getNodePresentation(BlockEnum.LoopEnd), {
    kind: 'terminal',
    showEntryShell: false,
    showTargetHandle: true,
    showSourceHandle: false,
    sourceHandleMode: 'none',
  })
})

test('round-trips the official custom-simple wire type and parent relationship', () => {
  const graph = {
    nodes: [{
      id: 'exit-1',
      type: 'custom-simple',
      parentId: 'loop-1',
      position: { x: 220, y: 100 },
      data: {
        type: BlockEnum.LoopEnd,
        title: '退出循环',
        loop_id: 'loop-1',
        future_field: true,
      },
    }],
    edges: [],
  }

  const flow = graphToFlow(graph)
  assert.equal(flow.nodes[0].type, BlockEnum.LoopEnd)
  assert.equal(flow.nodes[0].parentNode, 'loop-1')
  const output = flowToGraph(flow.nodes, flow.edges)
  assert.equal(output.nodes[0].type, 'custom-simple')
  assert.equal(output.nodes[0].parentId, 'loop-1')
  assert.equal(output.nodes[0].data.future_field, true)
})

test('wires the selector and core guard to the shared singleton rule', () => {
  const canvas = readFileSync(new URL('../../canvas/WorkflowCanvas.vue', import.meta.url), 'utf8')
  const selector = readFileSync(new URL('../../canvas/components/BlockSelectorMenu.vue', import.meta.url), 'utf8')
  const core = readFileSync(new URL('../../model/useWorkflowCore.js', import.meta.url), 'utf8')

  assert.match(canvas, /:allow-loop-end="selectorAllowsLoopEnd"/)
  assert.match(canvas, /canAddLoopEnd\(\{\s*nodes:\s*getNodes\.value,\s*parentId:\s*context\.parentId/)
  assert.match(selector, /type !== BlockEnum\.LoopEnd \|\| props\.allowLoopEnd/)
  assert.match(core, /type === BlockEnum\.LoopEnd && !canAddLoopEnd/)
})

test('checklist rejects loop-end outside a loop and duplicate exits', () => {
  const baseNodes = [
    { id: 'start', data: { type: BlockEnum.Start, title: 'Start' } },
    loop,
    { id: 'end', data: { type: BlockEnum.End, title: 'End', outputs: [] } },
  ]
  const orphan = { id: 'orphan', data: { type: BlockEnum.LoopEnd, title: '退出循环' } }
  const orphanIssues = buildWorkflowChecklist({ nodes: [...baseNodes, orphan], edges: [] })
  assert.ok(orphanIssues.some(issue => issue.id === 'loop-end-orphan'))

  const first = { id: 'exit-1', parentNode: loop.id, data: { type: BlockEnum.LoopEnd, title: '退出循环' } }
  const second = { id: 'exit-2', parentNode: loop.id, data: { type: BlockEnum.LoopEnd, title: '退出循环' } }
  const duplicateIssues = buildWorkflowChecklist({ nodes: [...baseNodes, first, second], edges: [] })
  assert.ok(duplicateIssues.some(issue => issue.id === 'loop-end-exit-1'))
  assert.ok(duplicateIssues.some(issue => issue.id === 'loop-end-exit-2'))
})
