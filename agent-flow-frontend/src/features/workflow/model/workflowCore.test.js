import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { BlockEnum } from './constants.js'
import { flowToGraph, generateNewNode, graphToFlow } from './dsl.js'
import { wouldCreateCycle } from './workflowInit.js'
import { shouldRejectDuplicateConnection } from './connectionValidation.js'
import {
  consumeSseText,
  encodeSensitiveField,
  getCsrfToken,
  isWriteMethod,
  parseSseBlock,
  sanitizeEnvironmentVariables,
  shouldConsumeAsSse,
} from '../../../shared/http/difyProtocol.js'

test('iteration nodes include a non-editable nested start node', () => {
  const { newNode, extraNodes } = generateNewNode({
    type: BlockEnum.Iteration,
    id: 'iteration-1',
    position: { x: 100, y: 120 },
  })

  assert.equal(extraNodes.length, 1)
  assert.equal(extraNodes[0].id, 'iteration-1start')
  assert.equal(extraNodes[0].parentNode, newNode.id)
  assert.equal(extraNodes[0].draggable, false)
  assert.equal(newNode.data.start_node_id, extraNodes[0].id)
})

test('graph conversion preserves Dify handles and removes runtime data', () => {
  const graph = {
    nodes: [
      {
        id: 'start',
        type: 'custom',
        position: { x: 0, y: 0 },
        data: { type: BlockEnum.Start, title: '开始', _runningStatus: 'running' },
      },
      {
        id: 'llm',
        type: 'custom',
        position: { x: 300, y: 0 },
        data: { type: BlockEnum.LLM, title: 'LLM' },
      },
    ],
    edges: [
      {
        id: 'start-source-llm-target',
        source: 'start',
        sourceHandle: 'source',
        target: 'llm',
        targetHandle: 'target',
      },
    ],
  }

  const flow = graphToFlow(graph)
  const output = flowToGraph(flow.nodes, flow.edges)

  assert.equal(output.edges[0].sourceHandle, 'source')
  assert.equal(output.edges[0].targetHandle, 'target')
  assert.equal(output.nodes[0].data._runningStatus, undefined)
  assert.equal(output.nodes[0].data.type, BlockEnum.Start)
})

test('cycle detection rejects a connection back to an ancestor', () => {
  const nodes = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
  const edges = [
    { source: 'a', target: 'b' },
    { source: 'b', target: 'c' },
  ]

  assert.equal(wouldCreateCycle(nodes, edges, { source: 'c', target: 'a' }), true)
  assert.equal(wouldCreateCycle(nodes, edges, { source: 'a', target: 'c' }), false)
})

test('setEdges re-apply keeps same-id edges; interactive duplicates stay blocked', () => {
  const existing = [{
    id: '1785216066534006-source-1785216077028007-target',
    source: '1785216066534006',
    target: '1785216077028007',
    sourceHandle: 'source',
    targetHandle: 'target',
  }]

  assert.equal(
    shouldRejectDuplicateConnection(existing[0], existing),
    false,
    're-applying the same edge id during setEdges must remain valid',
  )
  assert.equal(
    shouldRejectDuplicateConnection({
      source: '1785216066534006',
      target: '1785216077028007',
      sourceHandle: 'source',
      targetHandle: 'target',
    }, existing),
    true,
    'a new connection without id to the same endpoints must be blocked',
  )
})

test('note nodes round-trip with Dify custom-note node type', () => {
  const { newNode } = generateNewNode({
    type: BlockEnum.Note,
    id: 'note-1',
    position: { x: 120, y: 80 },
    data: { text: 'Remember this', theme: 'yellow' },
  })

  const graph = flowToGraph([newNode], [])
  assert.equal(graph.nodes[0].type, 'custom-note')
  assert.equal(graph.nodes[0].data.text, 'Remember this')

  const flow = graphToFlow(graph)
  assert.equal(flow.nodes[0].type, BlockEnum.Note)
  assert.equal(flow.nodes[0].data.theme, 'yellow')
})

test('new Dify node types receive usable defaults', () => {
  for (const type of [
    BlockEnum.Agent,
    BlockEnum.DataSource,
    BlockEnum.KnowledgeBase,
    BlockEnum.TriggerSchedule,
    BlockEnum.TriggerWebhook,
    BlockEnum.TriggerPlugin,
  ]) {
    const { newNode } = generateNewNode({ type, position: { x: 0, y: 0 } })
    assert.equal(newNode.data.type, type)
    assert.ok(newNode.data.title)
  }
})

test('canvas uses the Vue Flow drag-selection API and exposes variable management', () => {
  const canvasSource = readFileSync(new URL('../canvas/WorkflowCanvas.vue', import.meta.url), 'utf8')
  assert.match(canvasSource, /:selection-key-code=/)
  assert.doesNotMatch(canvasSource, /selection-on-drag=/)
  assert.match(canvasSource, /@variables="openVariables"/)
  assert.match(canvasSource, /v-model:active-tab="variablesTab"/)
  assert.match(canvasSource, /WorkflowVariablesPanel/)
})

test('graph import migrates legacy variable node types without changing their payloads', () => {
  const flow = graphToFlow({
    nodes: [
      {
        id: 'legacy-writer',
        type: 'custom',
        position: { x: 0, y: 0 },
        data: {
          type: 'variable-assigner',
          title: '旧变量赋值',
          version: '2',
          items: [{ variable_selector: ['conversation', 'history'] }],
        },
      },
      {
        id: 'legacy-aggregator',
        type: 'custom',
        position: { x: 240, y: 0 },
        data: {
          type: 'variable-aggregator',
          title: '旧变量聚合',
          output_type: 'string',
          variables: [['llm', 'text']],
        },
      },
    ],
    edges: [],
  })

  assert.equal(flow.nodes[0].type, BlockEnum.Assigner)
  assert.equal(flow.nodes[0].data.type, BlockEnum.Assigner)
  assert.deepEqual(flow.nodes[0].data.items, [{ variable_selector: ['conversation', 'history'] }])
  assert.equal(flow.nodes[1].type, BlockEnum.VariableAssigner)
  assert.equal(flow.nodes[1].data.type, BlockEnum.VariableAssigner)
  assert.deepEqual(flow.nodes[1].data.variables, [['llm', 'text']])

  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.type, 'assigner')
  assert.equal(exported.nodes[1].data.type, 'variable-assigner')
})

test('graph import lets ordinary node content define its measured height', () => {
  const graph = {
    nodes: [{
      id: 'human-input',
      type: 'custom',
      position: { x: 100, y: 80 },
      width: 244,
      height: 100,
      data: { type: BlockEnum.HumanInput, title: 'Human input' },
    }],
    edges: [],
  }

  const flow = graphToFlow(graph)

  assert.equal(flow.nodes[0].style?.height, undefined)
  assert.equal(flow.nodes[0].style?.width, undefined)
  assert.deepEqual(flow.nodes[0]._persistedSize, { width: 244, height: 100 })
  assert.equal(flowToGraph(flow.nodes, []).nodes[0].height, 100)
})

test('graph import keeps explicit dimensions for resizable containers', () => {
  const graph = {
    nodes: [{
      id: 'loop',
      type: 'custom',
      position: { x: 100, y: 80 },
      width: 900,
      height: 420,
      data: { type: BlockEnum.Loop, title: 'Loop' },
    }],
    edges: [],
  }

  const flow = graphToFlow(graph)

  assert.deepEqual(flow.nodes[0].style, { width: '900px', height: '420px' })
})

test('canvas chrome is split into controlled presentation components without changing public compatibility', () => {
  const canvasSource = readFileSync(new URL('../canvas/WorkflowCanvas.vue', import.meta.url), 'utf8')
  const railSource = readFileSync(new URL('../canvas/components/CanvasControlRail.vue', import.meta.url), 'utf8')

  assert.match(canvasSource, /CanvasControlRail/)
  assert.match(canvasSource, /CanvasOperatorDock/)
  assert.match(canvasSource, /WorkflowHeader/)
  assert.match(canvasSource, /publishing:\s*\{\s*type:\s*Boolean/)
  assert.match(canvasSource, /publishStatus:\s*\{\s*type:\s*String/)
  assert.match(canvasSource, /'publish'/)
  assert.match(canvasSource, /'back'/)
  assert.match(canvasSource, /defineExpose\([\s\S]*exportGraph/)
  assert.doesNotMatch(railSource, /评论模式/)
  assert.match(railSource, />Agent</)
})

test('Agent is a first-level rail action that follows the assistant panel width', () => {
  const canvasSource = readFileSync(new URL('../canvas/WorkflowCanvas.vue', import.meta.url), 'utf8')
  const railSource = readFileSync(new URL('../canvas/components/CanvasControlRail.vue', import.meta.url), 'utf8')

  assert.match(railSource, /aria-label="工作流 Agent"/)
  assert.match(railSource, /workflow-assist-panel-width/)
  assert.doesNotMatch(railSource, /more-wrap|moreOpen|更多画布工具|left:\s*416px/)
  assert.match(canvasSource, /:agent-panel-width="workflowAssist\.panelWidth"/)
})

test('available-variable composable resolves getter node ids', () => {
  const composableSource = readFileSync(new URL('./useAvailableVariables.js', import.meta.url), 'utf8')
  assert.match(composableSource, /toValue\(nodeId\)/)
  assert.doesNotMatch(composableSource, /unref\(nodeId\)/)
})

test('Dify auth protocol encodes UTF-8 and resolves CSRF cookies', () => {
  assert.equal(encodeSensitiveField('密码123'), Buffer.from('密码123').toString('base64'))
  assert.equal(getCsrfToken('csrf_token=normal; __Host-csrf_token=secure'), 'secure')
  assert.equal(isWriteMethod('POST'), true)
  assert.equal(isWriteMethod('get'), false)
})

test('secret environment values are masked after persistence', () => {
  const variables = sanitizeEnvironmentVariables([
    { id: 'secret-1', name: 'API_KEY', value_type: 'secret', value: 'plaintext' },
    { id: 'text-1', name: 'REGION', value_type: 'string', value: 'cn' },
  ])
  assert.equal(variables[0].value, '[__HIDDEN__]')
  assert.equal(variables[1].value, 'cn')
})

test('Dify SSE parser preserves incomplete frames and emits complete events', () => {
  const events = []
  let buffer = consumeSseText('data: {"event":"node_started"', event => events.push(event))
  assert.equal(events.length, 0)
  buffer = consumeSseText(`${buffer},"data":{"node_id":"node-1"}}\n\n`, event => events.push(event))
  assert.equal(buffer, '')
  assert.deepEqual(events, [{ event: 'node_started', data: { node_id: 'node-1' } }])
})

test('Dify SSE parser skips ping and broken JSON without aborting', () => {
  const events = []
  // Trailing blank line is required so the last frame is a complete SSE block.
  const mixed = [
    'event: ping',
    '',
    'data: {"event":"message","answer":"ok"}',
    '',
    'data: {not-json',
    '',
    'data: {"event":"workflow_finished","data":{"status":"succeeded"}}',
    '',
    '',
  ].join('\n')
  consumeSseText(mixed, event => events.push(event))
  assert.equal(events.length, 2)
  assert.equal(events[0].answer, 'ok')
  assert.equal(events[1].event, 'workflow_finished')
  assert.equal(parseSseBlock('event: ping'), null)
})

test('shouldConsumeAsSse tolerates missing content-type when body exists', () => {
  assert.equal(shouldConsumeAsSse({
    body: {},
    headers: { get: () => null },
  }), true)
  assert.equal(shouldConsumeAsSse({
    body: {},
    headers: { get: () => 'text/event-stream; charset=utf-8' },
  }), true)
  assert.equal(shouldConsumeAsSse({
    body: {},
    headers: { get: () => 'application/json' },
  }), false)
  assert.equal(shouldConsumeAsSse({
    body: null,
    headers: { get: () => 'text/event-stream' },
  }), false)
})

test('graph export keeps viewport and removes transient edge data', () => {
  const graph = flowToGraph(
    [{ id: 'a', type: 'start', position: { x: 0, y: 0 }, data: { type: BlockEnum.Start } }],
    [{ id: 'e', source: 'a', target: 'a', data: { label: 'edge', _hovering: true } }],
    { x: -20, y: 30, zoom: 0.75 },
  )
  assert.deepEqual(graph.viewport, { x: -20, y: 30, zoom: 0.75 })
  assert.equal(graph.edges[0].data.label, 'edge')
  assert.equal(graph.edges[0].data._hovering, undefined)
})
