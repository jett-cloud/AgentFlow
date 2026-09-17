import { BlockEnum } from './constants.js'

export const TRIGGER_NODE_TYPES = Object.freeze([
  BlockEnum.TriggerSchedule,
  BlockEnum.TriggerWebhook,
  BlockEnum.TriggerPlugin,
])

function nodeTypeOf(node) {
  return node?.data?.type || node?.type
}

export function isTriggerNode(nodeType) {
  return TRIGGER_NODE_TYPES.includes(nodeType)
}

export function isTriggerWorkflow(nodes = []) {
  return nodes.some(node => isTriggerNode(nodeTypeOf(node)))
}

export function canAddHumanInputWebApp(nodes = [], deliveryTypes = []) {
  if (deliveryTypes.includes('webapp'))
    return true
  return !isTriggerWorkflow(nodes)
}
