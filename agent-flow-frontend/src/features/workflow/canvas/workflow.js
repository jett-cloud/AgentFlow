// src/views/copilot/components/workflow/workflow.js
// 画布内核统一出口，方便外部按需导入

export * from '../model/constants.js'
export * from '../model/nodeMeta.js'
export {
  uid,
  generateNewNode,
  graphToFlow,
  flowToGraph,
  makeIterationStartNode,
  makeLoopStartNode,
} from '../model/dsl.js'
export { useWorkflowCore } from '../model/useWorkflowCore.js'
export { useAvailableVariables, buildAvailableVariables } from '../model/useAvailableVariables.js'
export * from '../model/variableOutputs.js'
export { preprocessFlowGraph, stripRuntimeNodeData, wouldCreateCycle } from '../model/workflowInit.js'
export { getNodeData, useResolvedNodeData } from '../model/nodeProps.js'
export { NODE_COMPONENT_MAP, PANEL_COMPONENT_MAP, EDGE_COMPONENT_MAP } from '../nodes/registry.js'
