import test from 'node:test'
import assert from 'node:assert/strict'
import { BlockEnum } from './constants.js'
import { getNodeOutputVars } from './variableOutputs.js'
import { formatWorkflowVarToken } from './promptVariableSyntax.js'
import {
  buildAvailableVariables,
  buildSpecialVarGroups,
  getGlobalVars,
  getVariableDisplayName,
  toValueSelector,
} from './availableVariables.js'

test('Start chat mode exposes sys.query and sys.files (not userinput.*)', () => {
  const vars = getNodeOutputVars({
    id: 'start',
    data: {
      type: BlockEnum.Start,
      variables: [{ variable: 'name', type: 'text-input', label: '姓名' }],
    },
  }, { isChatMode: true })

  assert.deepEqual(vars.map(v => v.variable), ['name', 'sys.query', 'sys.files'])
  assert.ok(!vars.some(v => v.variable.startsWith('userinput.')))
})

test('Start workflow mode exposes sys.files but not sys.query', () => {
  const vars = getNodeOutputVars({
    id: 'start',
    data: { type: BlockEnum.Start, variables: [] },
  }, { isChatMode: false })

  assert.deepEqual(vars.map(v => v.variable), ['sys.files'])
})

test('toValueSelector matches Dify getValueSelector for sys/env/node vars', () => {
  assert.deepEqual(toValueSelector('start', 'sys.query'), ['sys', 'query'])
  assert.deepEqual(toValueSelector('start', 'sys.files'), ['sys', 'files'])
  assert.deepEqual(toValueSelector('start', 'name'), ['start', 'name'])
  assert.deepEqual(toValueSelector('global', 'sys.user_id'), ['sys', 'user_id'])
  assert.deepEqual(toValueSelector('env', 'env.API_KEY'), ['env', 'API_KEY'])
  assert.deepEqual(
    toValueSelector('conversation', 'conversation.foo'),
    ['conversation', 'foo'],
  )
})

test('picking Start sys.query inserts {{#sys.query#}} token', () => {
  const selector = toValueSelector('start-node', 'sys.query')
  assert.equal(formatWorkflowVarToken(selector), '{{#sys.query#}}')
  assert.equal(getVariableDisplayName('sys.query'), 'query')
  assert.equal(getVariableDisplayName('sys.files'), 'files')
})

test('buildAvailableVariables includes Start sys.query for chat LLM downstream', () => {
  const groups = buildAvailableVariables({
    nodeId: 'llm-1',
    isChatMode: true,
    nodes: [
      { id: 'start', data: { type: BlockEnum.Start, title: '开始', variables: [] } },
      { id: 'llm-1', data: { type: BlockEnum.LLM, title: 'LLM' } },
    ],
    edges: [{ id: 'e1', source: 'start', target: 'llm-1' }],
  })
  const start = groups.find(g => g.nodeId === 'start')
  assert.ok(start)
  assert.ok(start.vars.some(v => v.variable === 'sys.query'))
  assert.ok(start.vars.some(v => v.variable === 'sys.files'))
})

test('getGlobalVars uses sys.* names and omits query/files', () => {
  const chat = getGlobalVars(true).map(v => v.variable)
  const workflow = getGlobalVars(false).map(v => v.variable)
  assert.ok(chat.includes('sys.dialogue_count'))
  assert.ok(chat.includes('sys.conversation_id'))
  assert.ok(chat.includes('sys.user_id'))
  assert.ok(!chat.includes('sys.query') && !chat.includes('query'))
  assert.ok(workflow.includes('sys.timestamp'))
  assert.ok(!workflow.includes('sys.dialogue_count'))
})

test('buildSpecialVarGroups prefixes env/conversation like Dify', () => {
  const groups = buildSpecialVarGroups({
    isChatMode: true,
    environmentVariables: [{ name: 'API_KEY', value_type: 'secret' }],
    conversationVariables: [{ name: 'turn', value_type: 'number' }],
  })
  assert.equal(groups[0].nodeId, 'env')
  assert.equal(groups[0].vars[0].variable, 'env.API_KEY')
  assert.equal(groups[1].nodeId, 'conversation')
  assert.equal(groups[1].vars[0].variable, 'conversation.turn')
  assert.equal(groups[2].nodeId, 'global')
  assert.ok(groups[2].vars.some(v => v.variable === 'sys.user_id'))
})

test('Start sys.files exposes file sub-variable children', () => {
  const vars = getNodeOutputVars({
    id: 'start',
    data: { type: BlockEnum.Start, variables: [] },
  }, { isChatMode: true })
  const files = vars.find(v => v.variable === 'sys.files')
  assert.ok(files?.children?.some(c => c.variable === 'name'))
})

test('ParameterExtractor includes common struct fields', () => {
  const vars = getNodeOutputVars({
    id: 'pe',
    data: {
      type: BlockEnum.ParameterExtractor,
      parameters: [{ name: 'city', type: 'string' }],
    },
  })
  assert.ok(vars.some(v => v.variable === 'city'))
  assert.ok(vars.some(v => v.variable === '__is_success'))
  assert.ok(vars.some(v => v.variable === '__reason'))
})

test('ListFilter exposes result/first_record/last_record', () => {
  const vars = getNodeOutputVars({
    id: 'lf',
    data: {
      type: BlockEnum.ListFilter,
      var_type: 'arrayString',
      item_var_type: 'string',
    },
  })
  assert.deepEqual(vars.map(v => v.variable), ['result', 'first_record', 'last_record'])
  assert.equal(vars[0].type, 'arrayString')
})

test('HumanInput exposes only persisted Dify outputs', () => {
  const vars = getNodeOutputVars({
    id: 'hi',
    data: { type: BlockEnum.HumanInput, user_actions: [{ id: 'approve' }] },
  })
  assert.ok(vars.some(v => v.variable === '__action_id'))
  assert.ok(vars.some(v => v.variable === '__action_value'))
  assert.ok(vars.some(v => v.variable === '__rendered_content'))
  assert.equal(vars.some(v => v.variable === 'approve_approved'), false)
  assert.equal(vars.some(v => v.variable === 'approve_comment'), false)
})

test('LLM structured_output children appear when enabled', () => {
  const vars = getNodeOutputVars({
    id: 'llm',
    data: {
      type: BlockEnum.LLM,
      structured_output_enabled: true,
      structured_output: {
        schema: {
          type: 'object',
          properties: { answer: { type: 'string' } },
        },
      },
    },
  })
  const so = vars.find(v => v.variable === 'structured_output')
  assert.ok(so)
  assert.equal(so.children?.schema?.properties?.answer?.type, 'string')
})

test('error_strategy appends exception vars', () => {
  const vars = getNodeOutputVars({
    id: 'code',
    data: {
      type: BlockEnum.Code,
      outputs: { result: { type: 'string' } },
      error_strategy: 'default-value',
    },
  })
  assert.ok(vars.some(v => v.variable === 'error_message'))
  assert.ok(vars.some(v => v.variable === 'error_type'))
})
