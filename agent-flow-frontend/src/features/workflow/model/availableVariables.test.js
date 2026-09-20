import test from 'node:test'
import assert from 'node:assert/strict'
import {
  collectUsedSelectors,
  filterVarGroupsByType,
  flattenVarsForPicker,
  isConversationVar,
  isENV,
  isGlobalVar,
  isRagVariableVar,
  isSelectorAvailable,
  isSpecialVarPrefix,
  isSystemVar,
  parseSelectorInput,
  toValueSelector,
  toValueSelectorFromPath,
  buildSpecialVarGroups,
  buildDirectChildOutputGroups,
  selectAvailableVariableGroups,
  resolveAvailableVariable,
} from './availableVariables.js'
import { getContainerInnerVars, getNodeOutputVars, normalizeVarChildren } from './variableOutputs.js'
import { isIterationArrayVariable } from '../nodes/iteration/iterationNode.js'
import { isFilteredVariableSelectable, mapGroupsToPickerRows } from './objectChildTree.js'

test('isSystemVar / isGlobalVar distinguish query/files from global sys vars', () => {
  assert.equal(isSystemVar(['sys', 'query']), true)
  assert.equal(isGlobalVar(['sys', 'query']), false)
  assert.equal(isGlobalVar(['sys', 'files']), false)
  assert.equal(isGlobalVar(['sys', 'user_id']), true)
  assert.equal(isSystemVar(['node', 'text']), false)
})

test('isENV / isConversationVar / isRagVariableVar / isSpecialVarPrefix', () => {
  assert.equal(isENV(['env', 'API_KEY']), true)
  assert.equal(isConversationVar(['conversation', 'topic']), true)
  assert.equal(isRagVariableVar(['rag', 'x']), true)
  assert.equal(isSpecialVarPrefix('sys'), true)
  assert.equal(isSpecialVarPrefix('env'), true)
  assert.equal(isSpecialVarPrefix('llm'), false)
})

test('parseSelectorInput normalizes string and array forms', () => {
  assert.deepEqual(parseSelectorInput('sys.query'), ['sys', 'query'])
  assert.deepEqual(parseSelectorInput(['sys', 'query']), ['sys', 'query'])
  assert.deepEqual(parseSelectorInput(''), [])
  assert.deepEqual(parseSelectorInput(null), [])
})

test('collectUsedSelectors finds value_selector arrays and {{#...#}} tokens', () => {
  const found = collectUsedSelectors({
    query_variable_selector: ['sys', 'query'],
    prompt_template: [
      { text: 'Hello {{#sys.query#}} and {{#llm.text#}}' },
    ],
    nested: {
      variables: [{ value_selector: ['start', 'name'] }],
    },
  })
  const keys = found.map(s => s.join('.')).sort()
  assert.deepEqual(keys, ['llm.text', 'start.name', 'sys.query'])
})

test('isSelectorAvailable accepts special prefixes and matching node outputs', () => {
  const groups = [
    { nodeId: 'llm', vars: [{ variable: 'text', type: 'string' }] },
    { nodeId: 'global', vars: [{ variable: 'sys.user_id', type: 'string' }] },
    { nodeId: 'start', vars: [{ variable: 'sys.files', type: 'arrayFile' }], isStartNode: true },
  ]
  assert.equal(isSelectorAvailable(['sys', 'query'], groups), false)
  assert.equal(isSelectorAvailable(['sys', 'user_id'], groups), true)
  assert.equal(isSelectorAvailable(['sys', 'files'], groups), true)
  assert.equal(isSelectorAvailable(['env', 'KEY'], groups), false)
  assert.equal(isSelectorAvailable(['llm', 'text'], groups), true)
  assert.equal(isSelectorAvailable(['llm', 'missing'], groups), false)
  assert.equal(isSelectorAvailable(['other', 'text'], groups), false)
})

test('filterVarGroupsByType keeps nested non-file children under hidden file parents', () => {
  const groups = [
    {
      nodeId: 'start',
      vars: [
        { variable: 'sys.query', type: 'string' },
        { variable: 'sys.files', type: 'arrayFile', children: [{ variable: 'name', type: 'string' }] },
      ],
    },
  ]
  const filtered = filterVarGroupsByType(groups, { hideFileVars: true })
  assert.ok(filtered[0].vars.some(v => v.variable === 'sys.query'))
  const files = filtered[0].vars.find(v => v.variable === 'sys.files')
  assert.ok(files)
  assert.ok(files.children?.some(c => c.variable === 'name'))
})

test('toValueSelector still maps special prefixes', () => {
  assert.deepEqual(toValueSelector('start', 'conversation.topic'), ['conversation', 'topic'])
  assert.deepEqual(toValueSelector('start', 'rag.doc'), ['rag', 'doc'])
})

test('flattenVarsForPicker expands file children into nested selectors', () => {
  const rows = flattenVarsForPicker([
    {
      variable: 'sys.files',
      type: 'arrayFile',
      children: [{ variable: 'name', type: 'string' }],
    },
  ])
  assert.ok(rows.some(r => r.displayPath === 'files' || r.selectorPath.join('.') === 'sys.files'))
  const nested = rows.find(r => r.selectorPath.join('.') === 'sys.files.name')
  assert.ok(nested)
  assert.deepEqual(
    toValueSelectorFromPath('start', nested.selectorPath),
    ['sys', 'files', 'name'],
  )
})

test('buildSpecialVarGroups includes shared RAG inputs', () => {
  const groups = buildSpecialVarGroups({
    ragPipelineVariables: [
      { belong_to_node_id: 'shared', variable: 'query', type: 'text-input', label: 'Query' },
      { belong_to_node_id: 'ds-1', variable: 'doc', type: 'file', label: 'Doc' },
    ],
  })
  const rag = groups.find(g => g.nodeId === 'rag')
  assert.ok(rag)
  assert.equal(rag.vars[0].variable, 'rag.shared.query')
  assert.ok(!rag.vars.some(v => v.variable.includes('ds-1')))
})

test('isSelectorAvailable matches nested children paths', () => {
  const groups = [{
    nodeId: 'http',
    vars: [{
      variable: 'files',
      type: 'arrayFile',
      children: [{ variable: 'name', type: 'string' }],
    }],
  }]
  assert.equal(isSelectorAvailable(['http', 'files', 'name'], groups), true)
  assert.equal(isSelectorAvailable(['http', 'files', 'missing'], groups), false)
})

test('collectUsedSelectors skips constants, schema lists, and multi-selector query', () => {
  const found = collectUsedSelectors({
    dataset_ids: ['dataset-a', 'dataset-b'],
    required: ['question', 'answer'],
    tool_parameters: {
      q: { type: 'constant', value: '{{#start.query#}}' },
      src: { type: 'variable', value: ['code', 'result'] },
    },
    query: [['llm_a', 'text'], ['llm_b', 'text']],
    variables: [['branch_a', 'text']],
  })
  const keys = found.map(s => s.join('.')).sort()
  assert.deepEqual(keys, ['branch_a.text', 'code.result'])
})

test('isSelectorAvailable allows object drill-down and rejects arrayObject', () => {
  const groups = [{
    nodeId: 'iter',
    vars: [
      { variable: 'item', type: 'object' },
      { variable: 'rows', type: 'arrayObject' },
    ],
  }]
  assert.equal(isSelectorAvailable(['iter', 'item', 'question'], groups), true)
  assert.equal(isSelectorAvailable(['iter', 'rows', 'question'], groups), false)
})

test('loop inner vars use labels and var_type, not synthetic item/index', () => {
  const loop = {
    id: 'loop1',
    data: {
      type: 'loop',
      loop_variables: [
        {
          label: 'state',
          var_type: 'object',
          value_type: 'constant',
          value: { count: 0 },
          children: { count: { type: 'number', children: null } },
        },
      ],
    },
  }
  const inner = getContainerInnerVars(loop)
  assert.deepEqual(inner.map(v => v.variable), ['state'])
  assert.equal(inner[0].type, 'object')
  assert.deepEqual(inner[0].children.map(v => v.variable), ['count'])
  const outputs = getNodeOutputVars(loop)
  assert.deepEqual(outputs.map(v => v.variable), ['state'])
  assert.equal(outputs[0].type, 'object')
  assert.deepEqual(outputs[0].children.map(v => v.variable), ['count'])
})

test('iteration item type comes from iterator element type', () => {
  const nodes = [
    {
      id: 'code1',
      data: { type: 'code', outputs: { rows: { type: 'array[object]', children: { question: { type: 'string' } } } } },
    },
    {
      id: 'iter1',
      data: { type: 'iteration', iterator_selector: ['code1', 'rows'] },
    },
  ]
  const inner = getContainerInnerVars(nodes[1], { nodes })
  const item = inner.find(v => v.variable === 'item')
  assert.equal(item.type, 'object')
  assert.ok(item.children?.some(child => child.variable === 'question'))
})

test('agent declared object arrays expose their item fields to iteration', () => {
  const nodes = [
    {
      id: 'agent1',
      data: {
        type: 'agent',
        agent_binding: { binding_type: 'inline_agent' },
        agent_declared_outputs: [{
          name: 'cases',
          type: 'array',
          array_item: {
            type: 'object',
            children: [{ name: 'question', type: 'string' }],
          },
        }],
      },
    },
    {
      id: 'iter1',
      data: { type: 'iteration', iterator_selector: ['agent1', 'cases'] },
    },
  ]

  const cases = getNodeOutputVars(nodes[0])[0]
  const item = getContainerInnerVars(nodes[1], { nodes }).find(v => v.variable === 'item')
  assert.equal(cases.type, 'arrayObject')
  assert.deepEqual(cases.children.map(child => child.variable), ['question'])
  assert.deepEqual(item.children.map(child => child.variable), ['question'])
})

test('container output scope contains direct children but not outside nodes', () => {
  const container = { id: 'iter-1', data: { type: 'iteration' } }
  const groups = buildDirectChildOutputGroups(container, [
    { id: 'inside', parentId: 'iter-1', data: { type: 'code', title: '内部代码', outputs: { result: { type: 'string' } } } },
    { id: 'outside', data: { type: 'code', title: '外部代码', outputs: { result: { type: 'string' } } } },
  ])
  assert.deepEqual(groups.map(group => group.nodeId), ['inside'])
})

test('direct-child picker scope excludes upstream and special groups', () => {
  const nodeGroups = [{ nodeId: 'outside' }]
  const directChildGroups = [{ nodeId: 'inside' }]
  const specialGroups = [{ nodeId: 'global' }]
  assert.deepEqual(selectAvailableVariableGroups({
    nodeGroups,
    directChildGroups,
    specialGroups,
    includeDirectChildren: true,
  }).map(group => group.nodeId), ['inside'])
  assert.deepEqual(selectAvailableVariableGroups({
    nodeGroups,
    directChildGroups,
    specialGroups,
    includeDirectChildren: false,
  }).map(group => group.nodeId), ['outside', 'global'])
})

test('normalizeVarChildren reads code output maps and ignores a Var-shaped object', () => {
  const fromCode = normalizeVarChildren({ question: { type: 'string' }, answer: { type: 'string' } })
  assert.deepEqual(fromCode.map(v => v.variable), ['question', 'answer'])
  assert.deepEqual(
    normalizeVarChildren({ variable: 'row', type: 'object' }),
    [],
  )
})

test('resolveAvailableVariable returns metadata for direct and nested selectors', () => {
  const groups = [{
    nodeId: 'code-1',
    vars: [{
      variable: 'rows',
      type: 'arrayObject',
      children: [{ variable: 'score', type: 'number' }],
    }],
  }, {
    nodeId: 'sys',
    vars: [{ variable: 'sys.files', type: 'arrayFile' }],
  }]

  assert.equal(resolveAvailableVariable(['code-1', 'rows'], groups)?.type, 'arrayObject')
  assert.equal(resolveAvailableVariable(['code-1', 'rows', 'score'], groups)?.type, 'number')
  assert.equal(resolveAvailableVariable(['sys', 'files'], groups)?.type, 'arrayFile')
  assert.equal(resolveAvailableVariable(['code-1', 'missing'], groups), null)
})

test('array filter keeps object ancestors so nested array fields stay pickable', () => {
  const groups = [{
    nodeId: 'start',
    title: 'Start',
    vars: [{
      variable: 'payload',
      type: 'object',
      children: [
        { variable: 'items', type: 'array[number]' },
        { variable: 'title', type: 'string' },
      ],
    }],
  }]
  const filtered = filterVarGroupsByType(groups, { filterVar: isIterationArrayVariable })
  const picker = mapGroupsToPickerRows(filtered)
  assert.equal(picker[0].rows[0].variable, 'payload')
  assert.equal(isFilteredVariableSelectable(picker[0].rows[0], isIterationArrayVariable), false)
  assert.deepEqual(
    (picker[0].rows[0].children || []).map(child => child.variable),
    ['items'],
  )
  const droppedByRootFilter = (filtered[0].vars || []).filter(isIterationArrayVariable)
  assert.equal(droppedByRootFilter.length, 0)
})
