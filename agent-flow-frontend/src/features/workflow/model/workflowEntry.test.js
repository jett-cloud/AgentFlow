import assert from 'node:assert/strict'
import test from 'node:test'
import { BlockEnum } from './constants.js'
import { canAddHumanInputWebApp, isTriggerWorkflow } from './workflowEntry.js'

test('isTriggerWorkflow follows official trigger types and ignores datasource', () => {
  assert.equal(isTriggerWorkflow([{ data: { type: BlockEnum.TriggerWebhook } }]), true)
  assert.equal(isTriggerWorkflow([{ data: { type: BlockEnum.TriggerSchedule } }]), true)
  assert.equal(isTriggerWorkflow([{ data: { type: BlockEnum.TriggerPlugin } }]), true)
  assert.equal(isTriggerWorkflow([{ data: { type: BlockEnum.DataSource } }]), false)
  assert.equal(isTriggerWorkflow([{ data: { type: BlockEnum.Start } }]), false)
  assert.equal(isTriggerWorkflow([]), false)
})

test('trigger workflows can keep an existing WebApp channel but cannot add one', () => {
  const nodes = [{ data: { type: BlockEnum.TriggerWebhook } }]
  assert.equal(canAddHumanInputWebApp(nodes, []), false)
  assert.equal(canAddHumanInputWebApp(nodes, ['webapp']), true)
  assert.equal(canAddHumanInputWebApp([{ data: { type: BlockEnum.Start } }], []), true)
})
