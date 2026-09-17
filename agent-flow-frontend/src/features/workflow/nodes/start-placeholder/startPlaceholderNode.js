import { BlockEnum } from '../../model/constants.js'

export const START_PLACEHOLDER_DEFAULTS = Object.freeze({
  title: 'Workflow start',
  desc: '',
})

export const START_PLACEHOLDER_REPLACEMENT_TYPES = Object.freeze([
  BlockEnum.Start,
  BlockEnum.TriggerSchedule,
  BlockEnum.TriggerWebhook,
  BlockEnum.TriggerPlugin,
])

export function normalizeStartPlaceholderData(data = {}) {
  return {
    ...START_PLACEHOLDER_DEFAULTS,
    ...data,
    type: BlockEnum.StartPlaceholder,
  }
}

export function getStartPlaceholderHint(selected) {
  return selected ? '从右侧面板选择开始节点' : '点击配置开始节点'
}

export function isStartPlaceholderReplacementType(type) {
  return START_PLACEHOLDER_REPLACEMENT_TYPES.includes(type)
}

export function replaceStartPlaceholderInNodes({ nodes = [], id, nextType, nextData = {} } = {}) {
  if (!isStartPlaceholderReplacementType(nextType)) return null
  const placeholder = nodes.find(node => node.id === id)
  const currentType = placeholder?.data?.type || placeholder?.type
  if (currentType !== BlockEnum.StartPlaceholder) return null

  let replacement = null
  const nextNodes = nodes.map((node) => {
    if (node.id !== id) {
      return {
        ...node,
        selected: false,
        data: { ...node.data, selected: false },
      }
    }

    replacement = {
      ...node,
      type: nextType,
      selected: true,
      data: {
        ...nextData,
        type: nextType,
        selected: true,
      },
    }
    return replacement
  })

  return { nodes: nextNodes, node: replacement }
}
