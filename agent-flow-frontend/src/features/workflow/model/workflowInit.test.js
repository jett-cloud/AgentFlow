import assert from 'node:assert/strict'
import test from 'node:test'
import { graphToFlow } from './dsl.js'
import { preprocessFlowGraph } from './workflowInit.js'

test('workflow init migrates legacy Human Input without requiring _targetBranches', () => {
  const { nodes } = graphToFlow({
    nodes: [{
      id: 'human-1',
      data: {
        type: 'human-input',
        delivery_methods: [{ id: 'webapp', type: 'web_app', enabled: true }],
        prompt: 'Hello',
        inputs: [{ type: 'text', output_variable_name: 'comment' }],
        user_actions: [{ id: 'approve', title: '同意', button_style: 'primary' }],
      },
    }],
    edges: [],
  })
  const processed = preprocessFlowGraph(nodes, [])
  const data = processed.nodes[0].data
  assert.equal(data.form_content, 'Hello')
  assert.equal(data.prompt, undefined)
  assert.equal(data.inputs[0].type, 'paragraph')
  assert.match(data.delivery_methods[0].id, /^[0-9a-f-]{36}$/i)
  assert.equal(data.delivery_methods[0].type, 'webapp')
})

test('import preserves a valid non-default iteration start id through workflow init', () => {
  const { nodes } = graphToFlow({
    nodes: [
      { id: 'iter-1', type: 'custom', data: { type: 'iteration', start_node_id: 'entry_uuid_1' } },
      { id: 'entry_uuid_1', type: 'custom-iteration-start', parentId: 'iter-1', data: { type: 'iteration-start' } },
    ],
    edges: [],
  })
  const processed = preprocessFlowGraph(nodes, [])
  assert.equal(processed.nodes.find(node => node.id === 'iter-1').data.start_node_id, 'entry_uuid_1')
})
