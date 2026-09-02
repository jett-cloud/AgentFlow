import assert from 'node:assert/strict'
import test from 'node:test'

import { BlockEnum } from '../../model/constants.js'
import { START_INITIAL_POSITION, flowToGraph, graphToFlow } from '../../model/dsl.js'
import {
  SELECTABLE_BLOCKS,
  canConnectAsSource,
  canConnectAsTarget,
  getDefaultNodeData,
} from '../../model/nodeMeta.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodePresentation } from '../../model/nodePresentation.js'
import {
  START_PLACEHOLDER_DEFAULTS,
  START_PLACEHOLDER_REPLACEMENT_TYPES,
  getStartPlaceholderHint,
  isStartPlaceholderReplacementType,
  replaceStartPlaceholderInNodes,
} from './startPlaceholderNode.js'

test('start placeholder uses the official Dify defaults and contextual hint', () => {
  assert.deepEqual(START_PLACEHOLDER_DEFAULTS, {
    title: 'Workflow start',
    desc: '',
  })
  assert.deepEqual(getDefaultNodeData(BlockEnum.StartPlaceholder), {
    type: BlockEnum.StartPlaceholder,
    title: 'Workflow start',
    desc: '',
  })
  assert.equal(getStartPlaceholderHint(true), '从右侧面板选择开始节点')
  assert.equal(getStartPlaceholderHint(false), '点击配置开始节点')
})

test('start placeholder is a singleton entry candidate without workflow handles', () => {
  assert.deepEqual(START_PLACEHOLDER_REPLACEMENT_TYPES, [
    BlockEnum.Start,
    BlockEnum.TriggerSchedule,
    BlockEnum.TriggerWebhook,
    BlockEnum.TriggerPlugin,
  ])
  assert.equal(isStartPlaceholderReplacementType(BlockEnum.Start), true)
  assert.equal(isStartPlaceholderReplacementType(BlockEnum.End), false)
  assert.equal(canConnectAsSource(BlockEnum.StartPlaceholder), false)
  assert.equal(canConnectAsTarget(BlockEnum.StartPlaceholder), false)
  assert.equal(SELECTABLE_BLOCKS.includes(BlockEnum.StartPlaceholder), false)
  assert.deepEqual(getNodeOutputBranches({ type: BlockEnum.StartPlaceholder }), [])
  assert.deepEqual(getNodePresentation(BlockEnum.StartPlaceholder), {
    kind: 'entry',
    showEntryShell: true,
    showTargetHandle: false,
    showSourceHandle: false,
    sourceHandleMode: 'none',
  })
})

test('empty workflow injects one client placeholder and export removes it with attached edges', () => {
  const flow = graphToFlow({ nodes: [], edges: [] })
  assert.equal(flow.nodes.length, 1)
  assert.equal(flow.nodes[0].data.type, BlockEnum.StartPlaceholder)
  assert.equal(flow.nodes[0].data.title, 'Workflow start')
  assert.equal(flow.nodes[0].selected, true)
  assert.deepEqual(flow.nodes[0].position, START_INITIAL_POSITION)

  const ordinaryNodes = [
    { id: 'llm', type: BlockEnum.LLM, position: { x: 400, y: 100 }, data: { type: BlockEnum.LLM, title: 'LLM' } },
    { id: 'end', type: BlockEnum.End, position: { x: 700, y: 100 }, data: { type: BlockEnum.End, title: 'End' } },
  ]
  const graph = flowToGraph([...flow.nodes, ...ordinaryNodes], [
    { id: 'placeholder-out', source: flow.nodes[0].id, target: 'llm' },
    { id: 'placeholder-in', source: 'llm', target: flow.nodes[0].id },
    { id: 'ordinary', source: 'llm', target: 'end' },
  ])

  assert.deepEqual(graph.nodes.map(node => node.id), ['llm', 'end'])
  assert.deepEqual(graph.edges.map(edge => edge.id), ['ordinary'])
})

test('replacement keeps node identity and rejects non-start node types', () => {
  const nodes = [
    {
      id: 'placeholder',
      type: BlockEnum.StartPlaceholder,
      position: { x: 80, y: 282 },
      selected: true,
      data: { type: BlockEnum.StartPlaceholder, title: 'Workflow start', selected: true },
    },
    {
      id: 'llm',
      type: BlockEnum.LLM,
      position: { x: 400, y: 282 },
      selected: true,
      data: { type: BlockEnum.LLM, title: 'LLM', selected: true },
    },
  ]

  assert.equal(replaceStartPlaceholderInNodes({
    nodes,
    id: 'placeholder',
    nextType: BlockEnum.End,
    nextData: { type: BlockEnum.End, title: 'End' },
  }), null)

  const result = replaceStartPlaceholderInNodes({
    nodes,
    id: 'placeholder',
    nextType: BlockEnum.Start,
    nextData: { type: BlockEnum.Start, title: 'Start', variables: [] },
  })

  assert.deepEqual(result.node, {
    id: 'placeholder',
    type: BlockEnum.Start,
    position: { x: 80, y: 282 },
    selected: true,
    data: { type: BlockEnum.Start, title: 'Start', variables: [], selected: true },
  })
  assert.equal(result.nodes[1].selected, false)
  assert.equal(result.nodes[1].data.selected, false)
  assert.equal(nodes[0].type, BlockEnum.StartPlaceholder)
})

test('import repairs incomplete placeholder data while preserving unknown client fields', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'placeholder',
      type: 'custom',
      position: { x: 80, y: 282 },
      data: {
        type: BlockEnum.StartPlaceholder,
        future_field: { enabled: true },
      },
    }],
    edges: [],
  })

  assert.equal(flow.nodes[0].data.type, BlockEnum.StartPlaceholder)
  assert.equal(flow.nodes[0].data.title, 'Workflow start')
  assert.equal(flow.nodes[0].data.desc, '')
  assert.deepEqual(flow.nodes[0].data.future_field, { enabled: true })
})
