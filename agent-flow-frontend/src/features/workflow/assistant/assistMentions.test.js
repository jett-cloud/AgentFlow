import test from 'node:test'
import assert from 'node:assert/strict'
import * as assistMentions from './assistMentions.js'

import {
  ASSIST_MENTION_LIMIT,
  catalogMentionItems,
  detectMentionTrigger,
  filterMentionGroups,
  serializeMentionReferences,
  splitTextByMentions,
} from './assistMentions.js'

const catalog = catalogMentionItems({
  nodes: [
    { id: 'n1', data: { title: '知识库检索', type: 'knowledge-retrieval' } },
    { id: 'n2', data: { title: 'LLM', type: 'llm' } },
  ],
  tools: [
    { provider_name: 'time', tool_name: 'current_time', tool_label: '当前时间' },
    { provider_id: 'uuid-should-not-win', provider_name: 'web', tool_name: 'search', tool_label: '网页搜索' },
  ],
  datasets: [
    { id: 'ds-1', name: '产品文档' },
  ],
})

test('detects @ after a line start or whitespace and captures the query', () => {
  assert.deepEqual(detectMentionTrigger('@'), { query: '', start: 0 })
  assert.deepEqual(detectMentionTrigger('把 @知识'), { query: '知识', start: 2 })
  assert.deepEqual(detectMentionTrigger('hello\n@llm'), { query: 'llm', start: 6 })
  assert.equal(detectMentionTrigger('hello@world'), null)
  assert.deepEqual(detectMentionTrigger('email @'), { query: '', start: 6 })
})

test('catalogues nodes, tools, and datasets with provider/tool ids', () => {
  assert.deepEqual(catalog.find(item => item.kind === 'node' && item.id === 'n1'), {
    kind: 'node',
    id: 'n1',
    label: '知识库检索',
  })
  assert.deepEqual(catalog.find(item => item.kind === 'tool' && item.tool_name === 'current_time'), {
    kind: 'tool',
    id: 'time/current_time',
    label: '当前时间',
    provider: 'time',
    tool_name: 'current_time',
  })
  assert.equal(catalog.find(item => item.kind === 'tool' && item.tool_name === 'search').id, 'web/search')
  assert.deepEqual(catalog.find(item => item.kind === 'dataset'), {
    kind: 'dataset',
    id: 'ds-1',
    label: '产品文档',
  })
})

test('inserts selected workflow nodes through the mention resource boundary', () => {
  const inserted = []

  assert.equal(typeof assistMentions.insertSelectedNodeMentions, 'function')
  const didInsert = assistMentions.insertSelectedNodeMentions?.({
    nodes: [
      { id: 'n1', data: { title: '知识库检索', type: 'knowledge-retrieval' } },
      { id: 'n2', data: { title: 'LLM', type: 'llm' } },
    ],
    nodeIds: ['n2', 'missing', 'n1', 'n2'],
    insertResource: resource => inserted.push(resource),
  })

  assert.equal(didInsert, true)
  assert.deepEqual(inserted, [
    { kind: 'node', id: 'n2', label: 'LLM' },
    { kind: 'node', id: 'n1', label: '知识库检索' },
  ])
})

test('filters mentions into node, tool, and dataset groups', () => {
  const groups = filterMentionGroups(catalog, '知识')
  assert.deepEqual(groups.map(group => group.kind), ['node', 'tool', 'dataset'])
  assert.deepEqual(groups.find(group => group.kind === 'node').items.map(item => item.id), ['n1'])
  assert.equal(groups.find(group => group.kind === 'dataset').items.length, 0)
  assert.equal(groups.find(group => group.kind === 'tool').items.length, 0)

  const datasets = filterMentionGroups(catalog, '产品')
  assert.deepEqual(datasets.find(group => group.kind === 'dataset').items.map(item => item.id), ['ds-1'])
})

test('serializes at most eight chip references and keeps inner labels readable', () => {
  const chips = [
    { dataset: { kind: 'node', id: 'n1' }, textContent: '知识库检索' },
    { dataset: { kind: 'tool', id: 'time/current_time', provider: 'time', toolName: 'current_time' }, textContent: '当前时间' },
    { dataset: { kind: 'dataset', id: 'ds-1' }, textContent: '产品文档' },
    { dataset: { kind: 'node', id: '' }, textContent: 'broken' },
  ]
  assert.deepEqual(serializeMentionReferences(chips), [
    { kind: 'node', id: 'n1', label: '知识库检索' },
    { kind: 'tool', id: 'time/current_time', label: '当前时间', provider: 'time', tool_name: 'current_time' },
    { kind: 'dataset', id: 'ds-1', label: '产品文档' },
  ])

  const overflow = Array.from({ length: ASSIST_MENTION_LIMIT + 2 }, (_, index) => ({
    dataset: { kind: 'node', id: `n${index}` },
    textContent: `N${index}`,
  }))
  assert.equal(serializeMentionReferences(overflow).length, ASSIST_MENTION_LIMIT)
})

test('splits user text so timeline chips restore at the label', () => {
  const parts = splitTextByMentions('把 知识库检索 接到 LLM', [
    { kind: 'node', id: 'n1', label: '知识库检索' },
  ])
  assert.deepEqual(parts, [
    { text: '把 ' },
    { text: '知识库检索', reference: { kind: 'node', id: 'n1', label: '知识库检索' } },
    { text: ' 接到 LLM' },
  ])
})
