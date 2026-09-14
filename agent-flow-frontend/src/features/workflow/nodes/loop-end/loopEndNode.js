import { BlockEnum } from '../../model/constants.js'

export const LOOP_END_DEFAULTS = Object.freeze({})

function getNodeType(node) {
  return node?.data?.type || node?.type
}

function getParentId(node) {
  return node?.parentNode || node?.parentId || node?.data?.loop_id || ''
}

export function normalizeLoopEndNodeData(data = {}) {
  return { ...data }
}

export function canAddLoopEnd({ nodes = [], parentId } = {}) {
  if (!parentId)
    return false

  const parent = nodes.find(node => node.id === parentId)
  if (getNodeType(parent) !== BlockEnum.Loop)
    return false

  return !nodes.some(node => (
    getNodeType(node) === BlockEnum.LoopEnd
    && getParentId(node) === parentId
  ))
}

export function canPasteLoopEnd(node, clipboardNodes = []) {
  const parentId = getParentId(node)
  if (!parentId)
    return false
  const parent = clipboardNodes.find(item => item.id === parentId)
  return getNodeType(parent) === BlockEnum.Loop
}

export function getLoopEndValidationErrors(node, nodes = []) {
  const wrapperParent = node?.parentNode || node?.parentId
  const parent = nodes.find(item => item.id === wrapperParent)
  if (!wrapperParent || getNodeType(parent) !== BlockEnum.Loop)
    return ['退出循环节点必须位于循环容器内']
  if (node?.data?.loop_id !== wrapperParent)
    return ['退出循环节点必须位于循环容器内']

  const siblingLoopEnds = nodes.filter(item => (
    getNodeType(item) === BlockEnum.LoopEnd
    && (item.parentNode || item.parentId) === wrapperParent
  ))
  if (siblingLoopEnds.length > 1)
    return ['同一循环容器只能有一个退出循环节点']

  return []
}
