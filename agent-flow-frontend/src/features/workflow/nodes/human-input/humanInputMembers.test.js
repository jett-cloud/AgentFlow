import assert from 'node:assert/strict'
import test from 'node:test'
import {
  filterWorkspaceMembers,
  memberSelectorOptions,
  replaceMemberRecipients,
  selectedMemberIds,
} from './humanInputMembers.js'

const members = [
  { id: 'm1', name: 'Ada Lovelace', email: 'ada@example.com' },
  { id: 'm2', name: 'Grace Hopper', email: 'grace@navy.mil' },
]

test('member selector searches name and email, keeps unknown selected ids, and does not drop externals', () => {
  assert.deepEqual(filterWorkspaceMembers(members, 'ada'), [members[0]])
  assert.deepEqual(filterWorkspaceMembers(members, 'navy'), [members[1]])
  assert.deepEqual(selectedMemberIds([
    { type: 'member', reference_id: 'm1' },
    { type: 'member', reference_id: 'missing' },
    { type: 'external', email: 'reviewer@example.com' },
  ]), ['m1', 'missing'])

  const options = memberSelectorOptions(members, ['m1', 'missing'])
  assert.deepEqual(options.map(item => item.id), ['m1', 'm2', 'missing'])
  assert.equal(options[2].unknown, true)

  assert.deepEqual(replaceMemberRecipients([
    { type: 'member', reference_id: 'old' },
    { type: 'external', email: 'reviewer@example.com' },
  ], ['m1', 'm1', 'missing']), [
    { type: 'member', reference_id: 'm1' },
    { type: 'member', reference_id: 'missing' },
    { type: 'external', email: 'reviewer@example.com' },
  ])
})

test('failed member loads must not replace recipients with an empty list', () => {
  const stored = [
    { type: 'member', reference_id: 'stored-1' },
    { type: 'external', email: 'keep@example.com' },
  ]
  assert.deepEqual(replaceMemberRecipients(stored, selectedMemberIds(stored)), stored)
  assert.notDeepEqual(replaceMemberRecipients(stored, []), stored)
})
