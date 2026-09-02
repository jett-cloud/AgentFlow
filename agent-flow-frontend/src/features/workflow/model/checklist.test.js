import test from 'node:test'
import assert from 'node:assert/strict'
import { buildWorkflowChecklist, groupChecklistIssues } from './checklist.js'
import { graphToFlow, flowToGraph } from './dsl.js'

test('empty graph reports error', () => {
  const issues = buildWorkflowChecklist({ nodes: [], edges: [] })
  assert.equal(issues[0]?.id, 'empty-graph')
})

test('start-placeholder is flagged as needing selection', () => {
  const issues = buildWorkflowChecklist({
    nodes: [{ id: 'ph', type: 'start-placeholder', data: { type: 'start-placeholder', title: '选择开始节点' } }],
    edges: [],
  })
  assert.ok(issues.some(item => item.id === 'pick-start'))
})

test('empty graph injects start-placeholder and export strips it', () => {
  const flow = graphToFlow({ nodes: [], edges: [] })
  assert.equal(flow.nodes.length, 1)
  assert.equal(flow.nodes[0].data.type, 'start-placeholder')
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes.length, 0)
})

test('detects missing end and orphan nodes', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      { id: 'llm', data: { type: 'llm', title: 'LLM' } },
    ],
    edges: [],
  })
  assert.ok(issues.some(item => item.id === 'missing-end'))
  assert.ok(issues.some(item => item.id === 'orphan-llm'))
})

test('accepts basic valid workflow shape', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'llm',
        data: {
          type: 'llm',
          title: 'LLM',
          model: { provider: 'openai', name: 'gpt-4o' },
          prompt_template: [{ role: 'user', text: 'Answer the question.' }],
        },
      },
      { id: 'end', data: { type: 'end', title: 'End', outputs: [{ variable: 'text', value_selector: ['llm', 'text'], value_type: 'string' }] } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm' },
      { id: 'e2', source: 'llm', target: 'end' },
    ],
  })
  assert.equal(issues.filter(item => item.level === 'error').length, 0)
})

test('flags llm nodes missing provider as error', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      { id: 'llm', data: { type: 'llm', title: 'LLM', model: { name: 'gpt-4o' } } },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm' },
      { id: 'e2', source: 'llm', target: 'end' },
    ],
  })
  assert.ok(issues.some(item => item.id === 'model-config-llm' && item.level === 'error'))
  assert.equal(issues.find(item => item.id === 'model-config-llm')?.nodeId, 'llm')
})

test('groupChecklistIssues merges node-scoped messages', () => {
  const groups = groupChecklistIssues([
    { id: 'a', level: 'error', message: 'm1', nodeId: 'n1', title: 'N1' },
    { id: 'b', level: 'warning', message: 'm2', nodeId: 'n1', title: 'N1' },
    { id: 'c', level: 'error', message: 'global' },
  ])
  assert.equal(groups.length, 2)
  const nodeGroup = groups.find(g => g.id === 'n1')
  assert.equal(nodeGroup.canNavigate, true)
  assert.equal(nodeGroup.level, 'error')
  assert.deepEqual(nodeGroup.messages, ['m1', 'm2'])
})

test('code and answer empty configs are flagged', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      { id: 'code', data: { type: 'code', title: 'Code', code: '' } },
      { id: 'answer', data: { type: 'answer', title: 'Answer', answer: '' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'code' },
      { id: 'e2', source: 'code', target: 'answer' },
    ],
  })
  assert.ok(issues.some(item => item.id === 'code-code'))
  assert.ok(issues.some(item => item.id === 'answer-answer'))
})

test('flags invalid upstream variable references', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'llm',
        data: {
          type: 'llm',
          title: 'LLM',
          model: { provider: 'openai', name: 'gpt-4o' },
          prompt_template: [{ text: '{{#missing.text#}}' }],
        },
      },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm' },
      { id: 'e2', source: 'llm', target: 'end' },
    ],
  })
  assert.ok(issues.some(item => item.id === 'invalid-var-llm' && item.level === 'error'))
})

test('allows sys / env special selectors without marking invalid', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'llm',
        data: {
          type: 'llm',
          title: 'LLM',
          model: { provider: 'openai', name: 'gpt-4o' },
          prompt_template: [{ text: '{{#sys.query#}}' }],
          query_variable_selector: ['sys', 'query'],
        },
      },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'llm' },
      { id: 'e2', source: 'llm', target: 'end' },
    ],
  }, { isChatMode: true })
  assert.equal(issues.filter(item => item.id?.startsWith('invalid-var-')).length, 0)
})

test('agent-v2 incomplete inline binding is error', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'agent',
        data: {
          type: 'agent',
          title: 'Agent',
          version: '2',
          agent_node_kind: 'dify_agent',
          agent_binding: { binding_type: 'inline_agent' },
        },
      },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'agent' },
      { id: 'e2', source: 'agent', target: 'end' },
    ],
  })
  const issue = issues.find(item => item.id === 'agent-agent')
  assert.ok(issue)
  assert.equal(issue.level, 'error')
})

test('agent-v2 inline binding without model is error', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'agent',
        data: {
          type: 'agent',
          title: 'Agent',
          version: '2',
          agent_node_kind: 'dify_agent',
          agent_binding: {
            binding_type: 'inline_agent',
            agent_id: 'a1',
            current_snapshot_id: 's1',
          },
        },
      },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'agent' },
      { id: 'e2', source: 'agent', target: 'end' },
    ],
  })
  assert.equal(issues.filter(item => item.id === 'agent-agent').length, 0)
  assert.ok(issues.some(item => item.id === 'agent-model-agent' && item.level === 'error'))
})

test('agent-v2 valid inline binding with model passes checklist', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'agent',
        data: {
          type: 'agent',
          title: 'Agent',
          version: '2',
          agent_node_kind: 'dify_agent',
          agent_binding: {
            binding_type: 'inline_agent',
            agent_id: 'a1',
            current_snapshot_id: 's1',
          },
          model: { provider: 'openai', name: 'gpt-4o' },
        },
      },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'agent' },
      { id: 'e2', source: 'agent', target: 'end' },
    ],
  })
  assert.equal(issues.filter(item => item.id === 'agent-agent').length, 0)
  assert.equal(issues.filter(item => item.id === 'agent-model-agent').length, 0)
})
