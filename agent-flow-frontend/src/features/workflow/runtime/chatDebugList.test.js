import test from 'node:test'
import assert from 'node:assert/strict'
import {
  appendChatTurn,
  clearChatList,
  updateLastAssistant,
} from './chatDebugList.js'

test('appendChatTurn adds user then streaming assistant', () => {
  const list = appendChatTurn([], '你好')
  assert.equal(list.length, 2)
  assert.equal(list[0].role, 'user')
  assert.equal(list[0].content, '你好')
  assert.deepEqual(list[0].message_files, [])
  assert.equal(list[1].role, 'assistant')
  assert.equal(list[1].content, '')
  assert.equal(list[1].status, 'streaming')
  assert.deepEqual(list[1].message_files, [])
})

test('appendChatTurn keeps prior turns', () => {
  let list = appendChatTurn([], '一')
  list = appendChatTurn(list, '二')
  assert.equal(list.length, 4)
  assert.equal(list[2].content, '二')
})

test('appendChatTurn attaches user message_files', () => {
  const list = appendChatTurn([], '看图', [{ id: 'f1', name: 'a.png', url: 'https://x/a.png' }])
  assert.equal(list[0].message_files.length, 1)
  assert.equal(list[0].message_files[0].name, 'a.png')
  assert.deepEqual(list[1].message_files, [])
})

test('updateLastAssistant patches content and status', () => {
  let list = appendChatTurn([], 'q')
  list = updateLastAssistant(list, {
    content: '答',
    status: 'succeeded',
    citation: [{ document_name: 'doc' }],
    message_files: [{ id: 'm1', name: 'out.png' }],
  })
  assert.equal(list[1].content, '答')
  assert.equal(list[1].status, 'succeeded')
  assert.equal(list[1].citation[0].document_name, 'doc')
  assert.equal(list[1].message_files[0].id, 'm1')
})

test('updateLastAssistant no-ops on empty or non-assistant last', () => {
  assert.deepEqual(updateLastAssistant([], { content: 'x' }), [])
  const onlyUser = [{ id: 'u', role: 'user', content: 'hi' }]
  assert.deepEqual(updateLastAssistant(onlyUser, { content: 'x' }), onlyUser)
})

test('clearChatList returns empty array', () => {
  assert.deepEqual(clearChatList(), [])
})
