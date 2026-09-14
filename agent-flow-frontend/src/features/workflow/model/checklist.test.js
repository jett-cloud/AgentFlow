import test from 'node:test'
import assert from 'node:assert/strict'
import { buildWorkflowChecklist, groupChecklistIssues } from './checklist.js'
import { graphToFlow, flowToGraph } from './dsl.js'

function buildHumanInputIssues(data = {}) {
  const humanData = {
    type: 'human-input',
    title: '审批',
    delivery_methods: [{ id: '6ba7b810-9dad-41d1-80b4-00c04fd430c8', type: 'webapp', enabled: true }],
    user_actions: [{ id: 'approve', title: '通过', button_style: 'primary' }],
    form_content: '',
    inputs: [],
    timeout: 3,
    timeout_unit: 'day',
    ...data,
  }
  return buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      { id: 'human-1', data: humanData },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'human-1' },
      { id: 'e2', source: 'human-1', sourceHandle: humanData.user_actions[0]?.id, target: 'end' },
    ],
  })
}

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
  assert.ok(issues.some(item => item.id === 'end-required' && item.level === 'error'))
  assert.ok(issues.some(item => item.id === 'orphan-llm'))
})

function buildEmptyPipelineGraph() {
  return {
    nodes: [
      { id: 'ds', data: { type: 'datasource', title: '数据源' } },
      { id: 'kb', data: { type: 'knowledge-index', title: '写入知识库' } },
    ],
    edges: [{ id: 'e1', source: 'ds', target: 'kb' }],
  }
}

test('pipeline checklist does not require an End node', () => {
  const issues = buildWorkflowChecklist(buildEmptyPipelineGraph(), { isPipelineFlow: true })
  assert.equal(issues.some(item => item.id === 'end-required'), false)
  assert.equal(issues.some(item => item.id === 'answer-required'), false)
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

test('flags incomplete Tool identity and accepts a filled Tool envelope', () => {
  const missing = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      { id: 'tool-1', data: { type: 'tool', title: '工具', provider_id: 'p' } },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'tool-1' },
      { id: 'e2', source: 'tool-1', target: 'end' },
    ],
  })
  assert.ok(missing.some(issue => issue.id === 'tool-tool-1' && issue.level === 'error'))

  const ok = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'tool-1',
        data: {
          type: 'tool',
          title: '搜索',
          provider_id: 'search',
          tool_name: 'search',
          tool_parameters: { query: { type: 'constant', value: false } },
          parameters: [{ name: 'query', type: 'boolean', form: 'form', required: true }],
        },
      },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'tool-1' },
      { id: 'e2', source: 'tool-1', target: 'end' },
    ],
  })
  assert.equal(ok.some(issue => String(issue.id).startsWith('tool-')), false)
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

test('human-input checklist rejects backend-invalid actions', () => {
  const invalidActions = [
    { id: '1-invalid', title: '通过', button_style: 'primary' },
    { id: 'approve', title: '', button_style: 'primary' },
    { id: 'approve', title: '通过', button_style: 'danger' },
    { id: 'a'.repeat(21), title: '通过', button_style: 'default' },
    { id: 'approve', title: 'a'.repeat(101), button_style: 'default' },
  ]
  for (const action of invalidActions) {
    const issues = buildHumanInputIssues({ user_actions: [action] })
    assert.ok(issues.some(issue => issue.id === 'human-actions-human-1'), JSON.stringify(action))
  }
})

test('human-input checklist rejects unsupported, incomplete, and duplicate fields', () => {
  const invalidInputSets = [
    [{ type: 'text', output_variable_name: 'comment' }],
    [{ type: 'files', output_variable_name: 'attachments' }],
    [{ type: 'paragraph', output_variable_name: '', default: { type: 'constant', selector: [], value: '' } }],
    [{ type: 'select', output_variable_name: 'decision' }],
    [{ type: 'select', output_variable_name: 'decision', option_source: { type: 'variable', selector: [], value: [] } }],
    [{ type: 'file-list', output_variable_name: 'attachments', allowed_file_types: ['image'], allowed_file_extensions: [], allowed_file_upload_methods: ['tool_file'], number_limits: 5 }],
    [{ type: 'file-list', output_variable_name: 'attachments', allowed_file_types: ['image'], allowed_file_extensions: [], allowed_file_upload_methods: ['local_file'], number_limits: 1.5 }],
  ]
  for (const inputs of invalidInputSets) {
    const issues = buildHumanInputIssues({ inputs })
    assert.ok(issues.some(issue => issue.id === 'human-input-fields-human-1'), JSON.stringify(inputs))
  }

  const duplicateIssues = buildHumanInputIssues({
    inputs: [
      { type: 'paragraph', output_variable_name: 'comment', default: { type: 'constant', selector: [], value: '' } },
      { type: 'paragraph', output_variable_name: 'comment', default: { type: 'constant', selector: [], value: '' } },
    ],
  })
  assert.ok(duplicateIssues.some(issue => issue.id === 'human-input-name-human-1'))
  assert.ok(buildHumanInputIssues({
    inputs: [{ type: 'paragraph', output_variable_name: '__action_id', default: { type: 'constant', selector: [], value: '' } }],
  }).some(issue => issue.id === 'human-input-fields-human-1'))
  assert.equal(buildHumanInputIssues({ _targetBranches: [{ id: 'stale' }] }).some(issue => issue.id === 'human-actions-human-1'), false)
})

test('human-input checklist uses the normalized email contract and integer timeout', () => {
  const invalidEmail = {
    id: '9ba7b810-9dad-41d1-80b4-00c04fd430c8',
    type: 'email',
    enabled: true,
    config: {
      recipients: { include_bound_group: true, items: [] },
      subject: '审批',
      body: '缺少链接占位符',
      debug_mode: false,
    },
  }
  assert.ok(buildHumanInputIssues({ delivery_methods: [invalidEmail] })
    .some(issue => issue.id === 'human-email-human-1'))
  assert.ok(buildHumanInputIssues({ delivery_methods: [{ ...invalidEmail, type: 'slack' }] })
    .some(issue => issue.id === 'human-delivery-human-1'))
  assert.ok(buildHumanInputIssues({ timeout: 1.5 })
    .some(issue => issue.id === 'human-timeout-human-1'))

  const legacyRecipientIssues = buildHumanInputIssues({
    delivery_methods: [{
      ...invalidEmail,
      config: {
        recipients: { whole_workspace: true, items: [] },
        subject: '审批',
        body: '打开 {{#url#}}',
      },
    }],
  })
  assert.equal(legacyRecipientIssues.some(issue => issue.id === 'human-email-human-1'), false)
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

test('loop break_conditions may read direct child outputs such as human-input __action_id', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'cutout_loop',
        data: {
          type: 'loop',
          title: '抠图循环',
          loop_count: 10,
          break_conditions: [{
            id: 'c1',
            comparison_operator: 'is',
            value: 'approve',
            variable_selector: ['cutout_review', '__action_id'],
          }],
        },
      },
      {
        id: 'cutout_review',
        parentId: 'cutout_loop',
        data: {
          type: 'human-input',
          title: '抠图审核',
          delivery_methods: [{ id: 'd1', type: 'webapp', enabled: true }],
          user_actions: [{ id: 'approve', title: '通过' }],
          timeout: 3,
          timeout_unit: 'day',
        },
      },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'cutout_loop' },
      { id: 'e2', source: 'cutout_loop', target: 'end' },
    ],
  })
  assert.equal(issues.filter(item => item.id === 'invalid-var-cutout_loop').length, 0)
})

function loopChecklistGraph(loopData, extraNodes = []) {
  return buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start', variables: [{ variable: 'q', type: 'string' }] } },
      {
        id: 'loop',
        data: {
          type: 'loop',
          title: '循环',
          loop_count: 2,
          break_conditions: [],
          ...loopData,
        },
      },
      ...extraNodes,
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'loop' },
      { id: 'e2', source: 'loop', target: 'end' },
    ],
  })
}

test('loop checklist rejects illegal variable types and constant shapes', () => {
  const issues = loopChecklistGraph({
    loop_variables: [
      { id: 'a', label: 'count', var_type: 'number', value_type: 'bogus', value: 1 },
      { id: 'b', label: 'name', var_type: 'file', value_type: 'constant', value: 'x' },
      { id: 'c', label: 'ok', var_type: 'number', value_type: 'constant', value: 'nope' },
      { id: 'd', label: 'items', var_type: 'array[string]', value_type: 'constant', value: { x: 1 } },
      { id: 'e', label: 'flag', var_type: 'boolean', value_type: 'constant', value: 'no' },
    ],
  })
  assert.ok(issues.some(item => item.id === 'loop-variable-value-type-loop'))
  assert.ok(issues.some(item => item.id === 'loop-variable-var-type-loop'))
  assert.ok(issues.some(item => item.id === 'loop-variable-constant-loop'))
})

test('loop loop_variables still cannot read child outputs at loop start', () => {
  const issues = buildWorkflowChecklist({
    nodes: [
      { id: 'start', data: { type: 'start', title: 'Start' } },
      {
        id: 'cutout_loop',
        data: {
          type: 'loop',
          title: '抠图循环',
          loop_count: 10,
          loop_variables: [{
            label: 'cutout_url',
            var_type: 'string',
            value_type: 'variable',
            value: ['cutout_review', '__action_id'],
          }],
        },
      },
      {
        id: 'cutout_review',
        parentId: 'cutout_loop',
        data: {
          type: 'human-input',
          title: '抠图审核',
          delivery_methods: [{ id: 'd1', type: 'webapp', enabled: true }],
          user_actions: [{ id: 'approve', title: '通过' }],
          timeout: 3,
          timeout_unit: 'day',
        },
      },
      { id: 'end', data: { type: 'end', title: 'End' } },
    ],
    edges: [
      { id: 'e1', source: 'start', target: 'cutout_loop' },
      { id: 'e2', source: 'cutout_loop', target: 'end' },
    ],
  })
  assert.ok(issues.some(item => (
    item.id === 'invalid-var-cutout_loop'
    && item.message.includes('cutout_review.__action_id')
  )))
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

function validIterationNodes(overrides = {}) {
  return [
    { id: 'start', data: { type: 'start', variables: [{ variable: 'items', type: 'array[number]' }] } },
    { id: 'iter-1', data: { type: 'iteration', iterator_selector: ['start', 'items'], iterator_input_type: 'array[number]', output_selector: ['child', 'result'], output_type: 'array[number]', parallel_nums: 10, ...overrides } },
    { id: 'iter-1start', parentNode: 'iter-1', data: { type: 'iteration-start' } },
    { id: 'child', parentNode: 'iter-1', data: { type: 'code', outputs: { result: { type: 'number' } } } },
    { id: 'outside-code', data: { type: 'code', outputs: { result: { type: 'number' } } } },
    { id: 'end', data: { type: 'end', outputs: [] } },
  ]
}

function validIterationEdges() {
  return [
    { source: 'start', target: 'iter-1' },
    { source: 'iter-1start', target: 'child' },
    { source: 'iter-1', target: 'end' },
  ]
}

test('iteration checklist accepts every official array input type', () => {
  for (const type of ['array', 'array[string]', 'array[number]', 'array[boolean]', 'array[object]', 'array[file]']) {
    const issues = buildWorkflowChecklist({
      nodes: validIterationNodes({ iterator_input_type: type }),
      edges: validIterationEdges(),
    })
    assert.equal(issues.some(issue => issue.id === 'iteration-variable-iter-1'), false)
    assert.equal(issues.some(issue => issue.id === 'iteration-input-type-iter-1'), false)
    assert.equal(issues.some(issue => issue.id === 'iteration-type-iter-1'), false)
  }
})

test('iteration output selector must reference its own direct child', () => {
  const issues = buildWorkflowChecklist({
    nodes: validIterationNodes({ output_selector: ['outside-code', 'result'] }),
    edges: validIterationEdges(),
  })
  assert.ok(issues.some(issue => issue.id === 'iteration-output-scope-iter-1'))
})

test('iteration checklist rejects a scalar iterator even when stored type is array', () => {
  const nodes = validIterationNodes({
    iterator_selector: ['start', 'count'],
    iterator_input_type: 'array',
  })
  nodes[0] = {
    ...nodes[0],
    data: {
      ...nodes[0].data,
      variables: [
        { variable: 'items', type: 'array[number]' },
        { variable: 'count', type: 'number' },
      ],
    },
  }
  const issues = buildWorkflowChecklist({ nodes, edges: validIterationEdges() })
  assert.ok(issues.some(issue => issue.id === 'iteration-input-type-iter-1'))
})

test('iteration checklist rejects an unofficial error handle mode', () => {
  const issues = buildWorkflowChecklist({
    nodes: validIterationNodes({ error_handle_mode: 'explode' }),
    edges: validIterationEdges(),
  })
  assert.ok(issues.some(issue => issue.id === 'iteration-error-mode-iter-1'))
})

function knowledgeRetrievalGraph(data = {}) {
  return {
    nodes: [
      { id: 'start', data: { type: 'start' } },
      {
        id: 'kr',
        data: {
          type: 'knowledge-retrieval',
          dataset_ids: ['ds-1'],
          query_variable_selector: [],
          query_attachment_selector: [],
          retrieval_mode: 'multiple',
          multiple_retrieval_config: { top_k: 4, reranking_enable: false },
          ...data,
        },
      },
      { id: 'end', data: { type: 'end', outputs: [{ variable: 'result', value_selector: ['kr', 'result'], value_type: 'array[object]' }] } },
    ],
    edges: [{ source: 'start', target: 'kr' }, { source: 'kr', target: 'end' }],
  }
}

test('knowledge retrieval requires a query or attachment input', () => {
  const issues = buildWorkflowChecklist(knowledgeRetrievalGraph())
  assert.ok(issues.some(issue => issue.id === 'kr-input-kr'))
})

test('knowledge retrieval accepts attachment-only input', () => {
  const issues = buildWorkflowChecklist(knowledgeRetrievalGraph({
    query_attachment_selector: ['sys', 'files'],
  }))
  assert.equal(issues.some(issue => issue.id === 'kr-input-kr'), false)
})
