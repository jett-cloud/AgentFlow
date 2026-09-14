import assert from 'node:assert/strict'
import test from 'node:test'

import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, graphToFlow } from '../../model/dsl.js'
import { getDefaultNodeData } from '../../model/nodeMeta.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  buildCodeRunInputs,
  CODE_INPUT_TYPES,
  CODE_OUTPUT_TYPE_OPTIONS,
  normalizeCodeNodeData,
  renameCodeOutput,
  setCodeErrorStrategy,
  syncCodeFunctionSignature,
  upsertCodeInput,
  upsertCodeOutput,
} from './codeNode.js'

// 1. generateNewNode 默认值
test('new code nodes use the Dify default contract', () => {
  assert.deepEqual(getDefaultNodeData('code'), {
    type: 'code',
    title: '代码执行',
    code_language: 'python3',
    code: '',
    variables: [],
    outputs: {},
  })
})

// 2. 归一化、旧字段迁移与面板纯函数
test('code normalization preserves unknown fields and official wire shapes', () => {
  assert.deepEqual(normalizeCodeNodeData({
    type: 'code',
    code_language: 'javascript',
    variables: [{ variable: 'query', value_selector: ['start', 'query'], value_type: 'string' }],
    outputs: { result: { type: 'string' } },
    error_strategy: 'none',
    default_value: { result: 'legacy' },
    custom_dify_field: { keep: true },
  }), {
    type: 'code',
    code_language: 'javascript',
    code: '',
    variables: [{ variable: 'query', value_selector: ['start', 'query'], value_type: 'string' }],
    outputs: { result: { type: 'string', children: null } },
    custom_dify_field: { keep: true },
  })
})

test('code panel updates inputs and outputs without deleting unknown fields', () => {
  const withInput = upsertCodeInput({
    type: 'code',
    custom_dify_field: { keep: true },
  }, 0, {
    variable: 'score',
    value_selector: ['previous', 'score'],
    value_type: 'number',
  })
  const withOutput = upsertCodeOutput(withInput, 'result', 'array[boolean]')

  assert.deepEqual(withOutput.variables, [{
    variable: 'score',
    value_selector: ['previous', 'score'],
    value_type: 'number',
  }])
  assert.deepEqual(withOutput.outputs, {
    result: { type: 'array[boolean]', children: null },
  })
  assert.deepEqual(withOutput.custom_dify_field, { keep: true })
  assert.ok(CODE_OUTPUT_TYPE_OPTIONS.some(item => item.value === 'boolean'))
  assert.ok(CODE_OUTPUT_TYPE_OPTIONS.some(item => item.value === 'array[boolean]'))
})

test('code input contract keeps file arrays but excludes unsupported single files', () => {
  assert.equal(CODE_INPUT_TYPES.has('file'), false)
  assert.equal(CODE_INPUT_TYPES.has('arrayFile'), true)
  assert.equal(CODE_INPUT_TYPES.has('arrayNumber'), true)
})

test('code output rename preserves its schema and unknown node fields', () => {
  const renamed = renameCodeOutput({
    type: 'code',
    outputs: { result: { type: 'object', children: null, custom_schema_flag: true } },
    custom_dify_field: 42,
  }, 'result', 'payload')
  assert.deepEqual(renamed.outputs, {
    payload: { type: 'object', children: null, custom_schema_flag: true },
  })
  assert.equal(renamed.custom_dify_field, 42)
})

test('code function signature follows declared input names and types', () => {
  const variables = [
    { variable: 'query', value_selector: ['start', 'query'], value_type: 'string' },
    { variable: 'scores', value_selector: ['start', 'scores'], value_type: 'array[number]' },
  ]
  assert.equal(
    syncCodeFunctionSignature('def main(old):\n    return {"result": old}\n', 'python3', variables),
    'def main(query: str, scores: list[float]):\n    return {"result": old}\n',
  )
  assert.equal(
    syncCodeFunctionSignature('function main(old) { return { result: old }; }', 'javascript', variables),
    'function main({query, scores}) { return { result: old }; }',
  )
})

test('code error strategy uses Dify wire values and typed default values', () => {
  const configured = setCodeErrorStrategy({
    type: 'code',
    outputs: {
      result: { type: 'string', children: null },
      count: { type: 'number', children: null },
    },
  }, 'default-value')
  assert.equal(configured.error_strategy, 'default-value')
  assert.deepEqual(configured.default_value, [
    { key: 'result', type: 'string', value: '' },
    { key: 'count', type: 'number', value: 0 },
  ])
  assert.equal(setCodeErrorStrategy(configured, 'none').error_strategy, undefined)
})

// 3. 输出变量合同
test('code outputs enter downstream variables with official types', () => {
  assert.deepEqual(getNodeOutputVars({
    id: 'code-1',
    data: {
      type: 'code',
      outputs: {
        result: { type: 'string', children: null },
        flags: { type: 'array[boolean]', children: null },
      },
    },
  }), [
    { variable: 'result', type: 'string', children: null },
    { variable: 'flags', type: 'arrayBoolean', children: null },
  ])
})

// 4. Handle 合同
test('code exposes only source unless fail-branch error handling is enabled', () => {
  assert.deepEqual(getNodeOutputBranches({ type: 'code' }), [
    { id: 'source', name: '', kind: 'normal' },
  ])
  assert.deepEqual(getNodeOutputBranches({ type: 'code', error_strategy: 'fail-branch' }), [
    { id: 'source', name: '', kind: 'normal' },
    { id: 'fail-branch', name: '失败', kind: 'failure' },
  ])
  assert.equal(getNodeOutputBranches({
    type: 'code',
    retry_config: { retry_enabled: true, max_retries: 3, retry_interval: 100 },
  }).some(branch => branch.id === 'retry'), false)
})

// 5. DSL round-trip
test('code DSL round-trip keeps official fields and unknown data', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'code-1',
      type: 'custom',
      position: { x: 10, y: 20 },
      data: {
        type: 'code',
        title: '代码执行',
        code_language: 'python3',
        code: 'def main():\n    return {"ok": True}',
        variables: [],
        outputs: { ok: { type: 'boolean' } },
        custom_dify_field: 42,
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.deepEqual(exported.nodes[0].data.outputs.ok, { type: 'boolean', children: null })
  assert.equal(exported.nodes[0].data.custom_dify_field, 42)
})

test('code single-run payload only contains declared input variables', () => {
  assert.deepEqual(buildCodeRunInputs({
    variables: [
      { variable: 'query', value_selector: ['start', 'query'] },
      { variable: 'limit', value_selector: ['start', 'limit'] },
    ],
  }, { query: 'hello', limit: 3, ignored: true }), {
    query: 'hello',
    limit: 3,
  })
})

function buildCodeWorkflow(data) {
  return {
    nodes: [
      { id: 'start', data: { type: 'start', title: '开始', variables: [] } },
      { id: 'code-1', data: { type: 'code', title: '代码执行', ...data } },
      { id: 'end', data: { type: 'end', title: '结束', outputs: [] } },
    ],
    edges: [
      { id: 'start-code', source: 'start', target: 'code-1' },
      { id: 'code-end', source: 'code-1', target: 'end' },
    ],
  }
}

// 6. checklist 非法与合法配置
test('code checklist blocks invalid language, variables, outputs, and empty code', () => {
  const issues = buildWorkflowChecklist(buildCodeWorkflow({
    code_language: 'ruby',
    code: '',
    variables: [
      { variable: '1bad', value_selector: [] },
      { variable: '1bad', value_selector: ['start', 'query'] },
    ],
    outputs: { 'bad-key': { type: 'file' } },
  }))
  const ids = issues.map(issue => issue.id)
  assert.ok(ids.includes('code-code-1'))
  assert.ok(ids.includes('code-language-code-1'))
  assert.ok(ids.includes('code-input-name-code-1'))
  assert.ok(ids.includes('code-input-selector-code-1'))
  assert.ok(ids.includes('code-input-duplicate-code-1'))
  assert.ok(ids.includes('code-output-code-1'))
})

test('code checklist accepts a complete official configuration', () => {
  const issues = buildWorkflowChecklist(buildCodeWorkflow({
    code_language: 'python3',
    code: 'def main(query: str):\n    return {"result": query}',
    variables: [{ variable: 'query', value_selector: ['sys', 'user_id'], value_type: 'string' }],
    outputs: { result: { type: 'string', children: null } },
  }))
  assert.equal(issues.filter(issue => issue.id.startsWith('code-')).length, 0)
})

test('code checklist allows executable code without declared outputs', () => {
  const issues = buildWorkflowChecklist(buildCodeWorkflow({
    code_language: 'javascript',
    code: 'function main() { return {} }',
    variables: [],
    outputs: {},
  }))

  assert.equal(issues.filter(issue => issue.id.startsWith('code-')).length, 0)
})
