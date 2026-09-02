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
} from './availableVariables.js'

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
  ]
  assert.equal(isSelectorAvailable(['sys', 'query'], groups), true)
  assert.equal(isSelectorAvailable(['env', 'KEY'], groups), true)
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
