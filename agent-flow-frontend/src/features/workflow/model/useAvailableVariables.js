// 计算当前节点可用的上游变量（供 VarReferencePicker / PromptVariableTextarea 使用）
import { computed, inject, toValue } from 'vue'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import { isChatflowMode } from './appModes.js'
import {
  buildAvailableVariables,
  buildSpecialVarGroups,
  filterVarGroupsByType,
  flattenVarsForPicker,
  toValueSelectorFromPath,
} from './availableVariables.js'

export {
  buildAvailableVariables,
  buildSpecialVarGroups,
  collectUsedSelectors,
  filterVarGroupsByType,
  flattenVarsForPicker,
  getBeforeNodeIds,
  getGlobalVars,
  getVariableDisplayName,
  isConversationVar,
  isENV,
  isGlobalVar,
  isRagVariableVar,
  isSelectorAvailable,
  isSpecialVarPrefix,
  isSystemVar,
  parseSelectorInput,
  toValueSelector,
  toValueSelectorFromPath,
  VAR_SHOW_NAME_MAP,
} from './availableVariables.js'

/**
 * composable：在 Panel 中使用，自动 inject 画布 graph 状态。
 * @param {import('vue').Ref<string>|string} nodeId
 * @param {{ hideFileVars?: boolean, filterVar?: (v: object) => boolean }} [options]
 */
export function useAvailableVariables(nodeId, options = {}) {
  const graph = inject('workflowGraph', null)
  const workflowMode = inject('workflowMode', null)
  const store = useWorkflowStore()

  const availableVarGroups = computed(() => {
    const id = toValue(nodeId)
    const mode = toValue(workflowMode) || 'workflow'
    const isChatMode = isChatflowMode(mode)
    const ragPipelineVariables = store.ragPipelineVariables || []

    const nodeGroups = graph
      ? buildAvailableVariables({
          nodeId: id,
          nodes: graph.getNodes?.() || [],
          edges: graph.getEdges?.() || [],
          isChatMode,
          ragPipelineVariables,
        })
      : []

    const specialGroups = buildSpecialVarGroups({
      isChatMode,
      environmentVariables: store.environmentVariables || [],
      conversationVariables: store.conversationVariables || [],
      ragPipelineVariables,
    })

    const groups = [...nodeGroups, ...specialGroups]
    const hideFileVars = toValue(options.hideFileVars) || false
    const filterVar = toValue(options.filterVar)
    if (!hideFileVars && typeof filterVar !== 'function')
      return groups
    return filterVarGroupsByType(groups, { hideFileVars, filterVar })
  })

  /** Flatten nested children; each option carries full value_selector. */
  const flatOptions = computed(() => {
    const opts = []
    for (const group of availableVarGroups.value) {
      for (const row of flattenVarsForPicker(group.vars)) {
        const selector = toValueSelectorFromPath(group.nodeId, row.selectorPath)
        opts.push({
          label: `${group.title} / ${row.displayPath}`,
          value: selector,
          nodeId: group.nodeId,
          variable: row.variable,
          displayName: row.displayPath,
          displayPath: row.displayPath,
          selectorPath: row.selectorPath,
          type: row.type,
          des: row.des,
          hasChildren: row.hasChildren,
        })
      }
    }
    return opts
  })

  return { availableVarGroups, flatOptions }
}
