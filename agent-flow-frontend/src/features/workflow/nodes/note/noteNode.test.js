import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { BlockEnum } from '../../model/constants.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { SELECTABLE_BLOCKS, canConnectAsSource, canConnectAsTarget } from '../../model/nodeMeta.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodePresentation } from '../../model/nodePresentation.js'
import {
  NOTE_DEFAULTS,
  NOTE_MIN_HEIGHT,
  NOTE_MIN_WIDTH,
  NOTE_THEMES,
  getResizedNoteSize,
  normalizeNoteData,
  noteTextToPlainText,
  plainTextToNoteEditorState,
} from './noteNode.js'

test('new notes use the official Dify defaults and cannot connect', () => {
  assert.deepEqual(NOTE_DEFAULTS, {
    title: '',
    desc: '',
    text: '',
    theme: 'blue',
    author: '我',
    showAuthor: true,
    width: 240,
    height: 88,
  })
  assert.deepEqual(NOTE_THEMES, ['blue', 'cyan', 'green', 'yellow', 'pink', 'violet'])
  assert.equal(NOTE_MIN_WIDTH, 240)
  assert.equal(NOTE_MIN_HEIGHT, 88)

  const { newNode } = generateNewNode({
    type: BlockEnum.Note,
    id: 'note-1',
    position: { x: 120, y: 80 },
  })
  assert.deepEqual(newNode.data, { type: BlockEnum.Note, ...NOTE_DEFAULTS })
  assert.equal(canConnectAsSource(BlockEnum.Note), false)
  assert.equal(canConnectAsTarget(BlockEnum.Note), false)
  assert.equal(SELECTABLE_BLOCKS.includes(BlockEnum.Note), false)
  assert.deepEqual(getNodeOutputBranches({ type: BlockEnum.Note }), [])
  assert.deepEqual(getNodePresentation(BlockEnum.Note), {
    kind: 'annotation',
    showEntryShell: false,
    showTargetHandle: false,
    showSourceHandle: false,
    sourceHandleMode: 'none',
  })
})

test('resizing accounts for canvas zoom and enforces the official minimum', () => {
  assert.deepEqual(getResizedNoteSize({
    width: 240,
    height: 88,
    deltaX: 80,
    deltaY: 40,
    zoom: 2,
  }), { width: 280, height: 108 })
  assert.deepEqual(getResizedNoteSize({
    width: 260,
    height: 120,
    deltaX: -500,
    deltaY: -500,
    zoom: 1,
  }), { width: 240, height: 88 })
})

test('normalization repairs invalid presentation values and preserves unknown fields', () => {
  assert.deepEqual(normalizeNoteData({
    type: BlockEnum.Note,
    title: '',
    theme: 'invalid',
    width: 100,
    height: 40,
    future_field: { enabled: true },
  }), {
    ...NOTE_DEFAULTS,
    type: BlockEnum.Note,
    title: '',
    theme: 'blue',
    width: 240,
    height: 88,
    future_field: { enabled: true },
  })
  assert.deepEqual(normalizeNoteData({ type: BlockEnum.Note }), {
    type: BlockEnum.Note,
    ...NOTE_DEFAULTS,
  })
})

test('custom-note DSL round-trip preserves data, dimensions, and unknown fields', () => {
  const graph = {
    nodes: [{
      id: 'note-1',
      type: 'custom-note',
      position: { x: 120, y: 80 },
      data: {
        type: BlockEnum.Note,
        title: '',
        text: 'Remember this',
        theme: 'violet',
        author: 'Alice',
        showAuthor: false,
        width: 320,
        height: 160,
        future_field: true,
      },
    }],
    edges: [],
  }

  const flow = graphToFlow(graph)
  assert.equal(flow.nodes[0].type, BlockEnum.Note)
  assert.equal(flow.nodes[0].data.width, 320)
  const output = flowToGraph(flow.nodes, flow.edges)
  assert.equal(output.nodes[0].type, 'custom-note')
  assert.equal(output.nodes[0].data.text, 'Remember this')
  assert.equal(output.nodes[0].data.future_field, true)
  assert.equal(output.nodes[0].data.width, 320)
  assert.equal(output.nodes[0].data.height, 160)
})

test('imports official custom-note data even when its business type is empty', () => {
  const flow = graphToFlow({
    nodes: [{
      id: 'official-note',
      type: 'custom-note',
      position: { x: 0, y: 0 },
      data: { type: '', text: 'Official note' },
    }],
    edges: [],
  })

  assert.equal(flow.nodes[0].type, BlockEnum.Note)
  assert.equal(flow.nodes[0].data.type, '')
  assert.equal(flow.nodes[0].data.theme, 'blue')
  assert.equal(flow.nodes[0].data.width, 240)
  assert.equal(flow.nodes[0].data.height, 88)
  assert.equal(flow.nodes[0].data.showAuthor, true)
})

test('selected notes expose persistent resize and the official editing actions', () => {
  const component = readFileSync(new URL('./NoteNode.vue', import.meta.url), 'utf8')
  const resizer = readFileSync(new URL('./NoteResizer.vue', import.meta.url), 'utf8')
  const core = readFileSync(new URL('../../model/useWorkflowCore.js', import.meta.url), 'utf8')
  const canvas = readFileSync(new URL('../../canvas/WorkflowCanvas.vue', import.meta.url), 'utf8')

  assert.match(component, /<NoteResizer/)
  assert.match(component, /aria-label="显示作者"/)
  assert.match(component, /aria-label="复制便签"/)
  assert.match(component, /aria-label="创建便签副本"/)
  assert.match(component, /core\?\.copyNode\?\.\(props\.id\)/)
  assert.match(component, /core\?\.duplicateNode\?\.\(props\.id\)/)
  assert.doesNotMatch(component, /resize:\s*both/)

  assert.match(resizer, /getResizedNoteSize/)
  assert.match(resizer, /core\?\.recordHistory\?\.\(\)/)
  assert.match(resizer, /record:\s*false/)
  assert.match(resizer, /updateNodeDimensions/)
  assert.match(core, /function copyNode\(id\)/)
  assert.match(canvas, /copyNode,/)
})

test('official Lexical note text is displayed as plain multiline text', () => {
  const officialText = JSON.stringify({
    root: {
      type: 'root',
      version: 1,
      children: [
        {
          type: 'paragraph',
          version: 1,
          children: [{ type: 'text', version: 1, text: 'First line' }],
        },
        {
          type: 'paragraph',
          version: 1,
          children: [{
            type: 'link',
            version: 1,
            children: [{ type: 'text', version: 1, text: 'Second line' }],
          }],
        },
      ],
    },
  })

  assert.equal(noteTextToPlainText(officialText), 'First line\nSecond line')
  assert.equal(noteTextToPlainText('legacy plain text'), 'legacy plain text')
  assert.equal(noteTextToPlainText(''), '')
})

test('edited note text is saved as Dify-compatible Lexical JSON', () => {
  const serialized = plainTextToNoteEditorState('First line\nSecond line')
  const state = JSON.parse(serialized)

  assert.equal(state.root.type, 'root')
  assert.equal(state.root.version, 1)
  assert.equal(state.root.children.length, 2)
  assert.equal(state.root.children[0].type, 'paragraph')
  assert.equal(state.root.children[0].children[0].text, 'First line')
  assert.equal(state.root.children[1].children[0].text, 'Second line')
  assert.equal(noteTextToPlainText(serialized), 'First line\nSecond line')
  assert.equal(plainTextToNoteEditorState(''), '')
})
