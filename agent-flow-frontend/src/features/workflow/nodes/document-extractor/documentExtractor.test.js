import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  DOCUMENT_EXTRACTOR_DEFAULTS,
  buildDocumentExtractorRunInputs,
  isDocumentExtractorInput,
  normalizeDocumentExtractorData,
  setDocumentExtractorVariable,
} from './documentExtractor.js'

test('new document-extractor nodes use Dify defaults', () => {
  const { newNode } = generateNewNode({ type: 'document-extractor', id: 'doc-1' })

  assert.deepEqual(DOCUMENT_EXTRACTOR_DEFAULTS, {
    variable_selector: [],
    is_array_file: false,
  })
  assert.deepEqual(newNode.data.variable_selector, [])
  assert.equal(newNode.data.is_array_file, false)
})

test('normalization preserves unknown Dify fields and clones selectors', () => {
  const source = {
    type: 'document-extractor',
    variable_selector: ['start', 'files'],
    is_array_file: true,
    future_field: { enabled: true },
  }
  const normalized = normalizeDocumentExtractorData(source)
  normalized.variable_selector.push('name')

  assert.deepEqual(source.variable_selector, ['start', 'files'])
  assert.deepEqual(normalized.future_field, { enabled: true })
})

test('only File and Array[File] variables are selectable', () => {
  assert.equal(isDocumentExtractorInput({ type: 'file' }), true)
  assert.equal(isDocumentExtractorInput({ type: 'arrayFile' }), true)
  assert.equal(isDocumentExtractorInput({ type: 'array[file]' }), true)
  assert.equal(isDocumentExtractorInput({ type: 'string' }), false)
})

test('selecting an input derives is_array_file from the resolved variable type', () => {
  const single = setDocumentExtractorVariable({}, ['upload', 'file'], 'file')
  const many = setDocumentExtractorVariable(single, ['start', 'files'], 'arrayFile')

  assert.equal(single.is_array_file, false)
  assert.equal(many.is_array_file, true)
  assert.deepEqual(many.variable_selector, ['start', 'files'])
})

test('document extractor output follows single or array file input', () => {
  assert.deepEqual(getNodeOutputVars({
    id: 'doc-1',
    data: { type: 'document-extractor', is_array_file: false },
  }), [{ variable: 'text', type: 'string', des: '提取的文本' }])
  assert.deepEqual(getNodeOutputVars({
    id: 'doc-1',
    data: { type: 'document-extractor', is_array_file: true },
  }), [{ variable: 'text', type: 'arrayString', des: '提取的文本' }])
})

test('DSL round-trip keeps official fields and unknown data', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'doc-1',
      type: 'custom',
      position: { x: 0, y: 0 },
      data: {
        type: 'document-extractor',
        title: 'Document extractor',
        variable_selector: ['start', 'files'],
        is_array_file: true,
        future_field: 'keep-me',
      },
    }],
    edges: [],
  })
  const exported = flowToGraph(flow.nodes, flow.edges)

  assert.deepEqual(exported.nodes[0].data.variable_selector, ['start', 'files'])
  assert.equal(exported.nodes[0].data.is_array_file, true)
  assert.equal(exported.nodes[0].data.future_field, 'keep-me')
})

test('single-node run only submits files', () => {
  assert.deepEqual(buildDocumentExtractorRunInputs({ files: [{ id: 'file-1' }], ignored: true }), {
    files: [{ id: 'file-1' }],
  })
})

test('checklist rejects a missing document input', () => {
  const nodes = [
    { id: 'start', data: { type: 'start', title: 'Start', variables: [] } },
    { id: 'doc-1', data: { type: 'document-extractor', title: 'Document extractor', variable_selector: [] } },
    { id: 'end', data: { type: 'end', title: 'End', outputs: [] } },
  ]
  const edges = [
    { id: 'e1', source: 'start', target: 'doc-1' },
    { id: 'e2', source: 'doc-1', target: 'end' },
  ]
  const issues = buildWorkflowChecklist({ nodes, edges })

  assert.ok(issues.some(issue => issue.id === 'document-variable-doc-1' && issue.level === 'error'))
})
