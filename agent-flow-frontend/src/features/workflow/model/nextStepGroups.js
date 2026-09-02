import { DEFAULT_SOURCE_HANDLE } from './constants.js'
import { getNodeOutputBranches } from './nodeHandleBranches.js'

export function getNextStepGroups({ nodeId, nodeData, nodes = [], edges = [] }) {
  const nodeMap = new Map(nodes.map(node => [node.id, node]))
  return getNodeOutputBranches(nodeData).map(output => ({
    ...output,
    nextNodes: edges
      .filter(edge => (
        edge.source === nodeId
        && (edge.sourceHandle || DEFAULT_SOURCE_HANDLE) === output.id
      ))
      .map(edge => nodeMap.get(edge.target))
      .filter(Boolean),
  }))
}
