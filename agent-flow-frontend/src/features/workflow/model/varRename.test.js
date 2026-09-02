import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  rewriteSelector,
  rewriteVarTokens,
  rewriteVarReferencesInNodeData,
  buildOutVarSelectors,
  detectOutVarRename,
} from './varRename.js'

const here = dirname(fileURLToPath(import.meta.url))

test('rewriteSelector replaces a matching prefix and nested path', () => {
  assert.deepEqual(
    rewriteSelector(['start-1', 'query'], ['start-1', 'query'], ['start-1', 'prompt']),
    ['start-1', 'prompt'],
  )
  assert.deepEqual(
    rewriteSelector(['start-1', 'query', 'name'], ['start-1', 'query'], ['start-1', 'prompt']),
    ['start-1', 'prompt', 'name'],
  )
  assert.deepEqual(
    rewriteSelector(['other', 'query'], ['start-1', 'query'], ['start-1', 'prompt']),
    ['other', 'query'],
  )
})

test('rewriteVarTokens updates exact and nested {{#node.var#}} tokens', () => {
  assert.equal(
    rewriteVarTokens('Hello {{#start-1.query#}}', ['start-1', 'query'], ['start-1', 'prompt']),
    'Hello {{#start-1.prompt#}}',
  )
  assert.equal(
    rewriteVarTokens('{{#start-1.query.name#}}', ['start-1', 'query'], ['start-1', 'prompt']),
    '{{#start-1.prompt.name#}}',
  )
  assert.equal(
    rewriteVarTokens('keep {{#start-1.query2#}}', ['start-1', 'query'], ['start-1', 'prompt']),
    'keep {{#start-1.query2#}}',
  )
})

test('renaming an upstream output rewrites downstream selectors and prompts', () => {
  const { oldSelector, newSelector } = buildOutVarSelectors('start-1', 'query', 'prompt')
  const end = rewriteVarReferencesInNodeData({
    type: 'end',
    outputs: [{ variable: 'text', value_selector: ['start-1', 'query'] }],
  }, oldSelector, newSelector)
  const llm = rewriteVarReferencesInNodeData({
    type: 'llm',
    prompt_template: [{ role: 'user', text: 'Q: {{#start-1.query#}}' }],
    context: { variable_selector: ['start-1', 'query'] },
  }, oldSelector, newSelector)
  const code = rewriteVarReferencesInNodeData({
    type: 'code',
    variables: [{ variable: 'arg1', value_selector: ['start-1', 'query'] }],
  }, oldSelector, newSelector)
  const start = rewriteVarReferencesInNodeData({
    type: 'start',
    variables: [{ variable: 'prompt', label: 'Prompt', type: 'text-input' }],
  }, oldSelector, newSelector)

  assert.deepEqual(end.outputs[0].value_selector, ['start-1', 'prompt'])
  assert.equal(llm.prompt_template[0].text, 'Q: {{#start-1.prompt#}}')
  assert.deepEqual(llm.context.variable_selector, ['start-1', 'prompt'])
  assert.deepEqual(code.variables[0].value_selector, ['start-1', 'prompt'])
  assert.equal(start.variables[0].variable, 'prompt')
})

test('parameter extractor query arrays are rewritten even without selector in the key', () => {
  const next = rewriteVarReferencesInNodeData({
    type: 'parameter-extractor',
    query: ['code-1', 'result'],
  }, ['code-1', 'result'], ['code-1', 'payload'])
  assert.deepEqual(next.query, ['code-1', 'payload'])
})

test('detectOutVarRename finds a single renamed start or code output', () => {
  assert.deepEqual(
    detectOutVarRename(
      { type: 'start', variables: [{ variable: 'query' }] },
      { type: 'start', variables: [{ variable: 'prompt' }] },
    ),
    { oldName: 'query', newName: 'prompt' },
  )
  assert.deepEqual(
    detectOutVarRename(
      { type: 'code', outputs: { result: { type: 'string' } } },
      { type: 'code', outputs: { payload: { type: 'string' } } },
    ),
    { oldName: 'result', newName: 'payload' },
  )
  assert.equal(
    detectOutVarRename(
      { type: 'code', outputs: { result: { type: 'string' } } },
      { type: 'code', outputs: { result: { type: 'string' }, extra: { type: 'string' } } },
    ),
    null,
  )
})

test('workflow core applies downstream rewrite when node data updates', () => {
  const core = readFileSync(join(here, './useWorkflowCore.js'), 'utf8')
  assert.match(core, /detectOutVarRename/)
  assert.match(core, /handleOutVarRenameChange/)
})
