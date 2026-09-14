// src/views/copilot/components/workflow/core/useWorkflowCore.js
//
// 画布交互内核（composable）。必须在使用了 <VueFlow> 的组件 setup 中调用，
// 因为它依赖 useVueFlow() 的依赖注入。
//
// 提供：初始化/导出 DSL、增删节点与边、连线校验、复制/粘贴/克隆、撤销/重做、快捷键。
// live 的 nodes/edges 交给 vue-flow 持有；历史快照/选中/剪贴板存于 Pinia。

import { onMounted, onUnmounted } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { useWorkflowStore } from '@/features/workflow/state/useWorkflowStore.js'
import {
  BlockEnum,
  DEFAULT_SOURCE_HANDLE,
  DEFAULT_TARGET_HANDLE,
  CUSTOM_EDGE,
} from './constants.js'
import { canConnectAsSource, canConnectAsTarget, isContainerStartNode, getDefaultNodeData } from './nodeMeta.js'
import { generateNewNode, graphToFlow, flowToGraph, isStartPlaceholderNode, uid } from './dsl.js'
import { wouldCreateCycle } from './workflowInit.js'
import { shouldRejectDuplicateConnection } from './connectionValidation.js'
import { getConnectedNodePosition, getPredecessorNodePosition } from './connectedNodePlacement.js'
import { shouldConnectContainerStart } from './containerChildConnection.js'
import { getEdgesAfterNodeDataUpdate } from './nodeHandleBranches.js'
import { canAddLoopEnd, canPasteLoopEnd } from '../nodes/loop-end/loopEndNode.js'
import { replaceStartPlaceholderInNodes } from '../nodes/start-placeholder/startPlaceholderNode.js'
import { buildOutVarSelectors, detectOutVarRename, rewriteVarReferencesInNodeData } from './varRename.js'

const OFFSET = 40 // 粘贴/克隆时的位置偏移

export function useWorkflowCore(options = {}) {
  const store = useWorkflowStore()
  const vf = useVueFlow(options.vueFlowId)
  const {
    getNodes,
    getEdges,
    getSelectedNodes,
    getSelectedEdges,
    setNodes,
    setEdges,
    addNodes,
    addEdges,
    removeNodes,
    removeEdges,
    findNode,
    updateNodeData: vfUpdateNodeData,
    screenToFlowCoordinate,
    viewport,
    setViewport,
  } = vf

  // ---------------------------------------------------------------------------
  // 快照 / 历史（历史里存后端 graph 格式，round-trip 干净、天然与后端对齐）
  // ---------------------------------------------------------------------------
  function snapshot() {
    return flowToGraph(getNodes.value, getEdges.value, viewport.value)
  }

  function restore(graph) {
    const { nodes, edges, viewport: savedViewport } = graphToFlow(graph)
    setNodes(nodes)
    setEdges(edges)
    if (savedViewport)
      setViewport(savedViewport)
  }

  /** 在“结构性变更前”调用，把当前状态压入历史 */
  function recordHistory() {
    store.record(snapshot())
  }

  function undo() {
    const prev = store.undo(snapshot())
    if (prev) restore(prev)
  }

  function redo() {
    const next = store.redo(snapshot())
    if (next) restore(next)
  }

  // ---------------------------------------------------------------------------
  // 初始化 / 导出
  // ---------------------------------------------------------------------------
  function initFromGraph(graph, meta = {}) {
    const { nodes, edges, viewport: savedViewport } = graphToFlow(graph || { nodes: [], edges: [] })
    // Clear edges first so Vue Flow's setEdges + isValidConnection path cannot
    // treat re-applied edges as illegal duplicates (which drops all lines).
    setEdges([])
    setNodes(nodes)
    setEdges(edges)
    if (savedViewport)
      setViewport(savedViewport)
    store.setMeta(meta)
    store.resetHistory()
    store.setSelectedNodeId(null)
  }

  function exportGraph() {
    return snapshot()
  }

  // ---------------------------------------------------------------------------
  // 增删节点
  // ---------------------------------------------------------------------------
  /**
   * 新增节点。position 为画布坐标；若传 screenPosition 则自动换算。
   * parentId 指定则作为容器子节点加入。
   */
  function addNode(type, {
    position,
    screenPosition,
    parentId,
    connectionSourceId,
    data,
    record = true,
  } = {}) {
    if (store.readOnly) return null
    if (type === BlockEnum.LoopEnd && !canAddLoopEnd({ nodes: getNodes.value, parentId }))
      return null
    if (record) recordHistory()
    let pos = position
    if (!pos && screenPosition) pos = screenToFlowCoordinate(screenPosition)
    if (!pos) pos = { x: 100, y: 100 }

    const { newNode, extraNodes } = generateNewNode({ type, position: pos, data })

    if (parentId) {
      const parent = findNode(parentId)
      if (parent) {
        newNode.parentNode = parentId
        newNode.extent = 'parent'
        // 换算成相对父容器的坐标
        newNode.position = {
          x: Math.max(60, pos.x - (parent.position?.x || 0)),
          y: Math.max(60, pos.y - (parent.position?.y || 0)),
        }
        if (parent.data?.type === BlockEnum.Iteration || parent.type === BlockEnum.Iteration) {
          newNode.data.isInIteration = true
          newNode.data.iteration_id = parentId
        }
        if (parent.data?.type === BlockEnum.Loop || parent.type === BlockEnum.Loop) {
          newNode.data.isInLoop = true
          newNode.data.loop_id = parentId
        }
      }
    }

    addNodes([newNode, ...extraNodes])

    // 容器内首次添加：自动接到 iteration/loop start
    if (parentId) {
      const parent = findNode(parentId)
      const startId = parent?.data?.start_node_id
      if (shouldConnectContainerStart({ parentId, startId, connectionSourceId }) && findNode(startId)) {
        onConnect({
          source: startId,
          sourceHandle: DEFAULT_SOURCE_HANDLE,
          target: newNode.id,
          targetHandle: DEFAULT_TARGET_HANDLE,
        }, { record: false })
      }
    }

    return newNode
  }

  function removeNode(id) {
    if (store.readOnly) return
    const node = findNode(id)
    if (!node) return
    // 容器内的虚拟起始节点不可单独删除
    if (isContainerStartNode(node.data?.type)) return
    recordHistory()

    // 若删的是容器，连同其子节点一起删
    const idsToRemove = [id]
    if (node.data?.type === BlockEnum.Iteration || node.data?.type === BlockEnum.Loop) {
      getNodes.value.forEach((n) => {
        if ((n.parentNode || n.parentId) === id) idsToRemove.push(n.id)
      })
    }
    // Vue Flow 不会随节点自动删边，需手动清理关联边
    const idSet = new Set(idsToRemove)
    const edgeIds = getEdges.value
      .filter((e) => idSet.has(e.source) || idSet.has(e.target))
      .map((e) => e.id)
    if (edgeIds.length) removeEdges(edgeIds)
    removeNodes(idsToRemove)
    if (store.selectedNodeId && idsToRemove.includes(store.selectedNodeId))
      store.setSelectedNodeId(null)
  }

  function removeEdge(id) {
    if (store.readOnly) return
    recordHistory()
    removeEdges([id])
  }

  function updateNodeData(id, patch, { record = true } = {}) {
    if (store.readOnly) return
    const node = findNode(id)
    if (!node) return
    if (record) recordHistory()
    // Panels often emit a full data object; merge onto current node data.
    const previousData = node.data
    const nextData = { ...previousData, ...(patch || {}) }
    const renamed = detectOutVarRename(previousData, nextData)
    const edgeUpdate = getEdgesAfterNodeDataUpdate({
      nodeId: id,
      previousData,
      nextData,
      edges: getEdges.value,
    })
    nextData._connectedSourceHandleIds = edgeUpdate.connectedSourceHandleIds
    if (edgeUpdate.remappedEdges?.length) {
      for (const mapped of edgeUpdate.remappedEdges) {
        const edge = getEdges.value.find(item => item.id === mapped.id)
        if (edge)
          edge.sourceHandle = mapped.sourceHandle
      }
    }
    if (edgeUpdate.removedEdgeIds.length) {
      removeEdges(edgeUpdate.removedEdgeIds)
      for (const targetId of edgeUpdate.affectedTargetIds) {
        const targetHandles = [...new Set(
          edgeUpdate.edges
            .filter(edge => edge.target === targetId)
            .map(edge => edge.targetHandle || DEFAULT_TARGET_HANDLE),
        )]
        vfUpdateNodeData(targetId, { _connectedTargetHandleIds: targetHandles })
      }
    }
    vfUpdateNodeData(id, nextData)
    // Ensure vue-flow keeps a replaced data reference for panel reactivity.
    if (node.data)
      Object.assign(node.data, nextData)
    if (renamed)
      handleOutVarRenameChange(id, renamed.oldName, renamed.newName)
  }

  /** Rewrite downstream selectors/tokens after an output var is renamed. Does not record history. */
  function handleOutVarRenameChange(nodeId, oldName, newName) {
    if (store.readOnly || !nodeId || !oldName || oldName === newName)
      return
    const { oldSelector, newSelector } = buildOutVarSelectors(nodeId, oldName, newName)
    for (const node of getNodes.value) {
      const nextData = rewriteVarReferencesInNodeData(node.data, oldSelector, newSelector)
      if (nextData === node.data)
        continue
      vfUpdateNodeData(node.id, nextData)
      if (node.data)
        Object.assign(node.data, nextData)
    }
  }

  /**
   * 将 start-placeholder 原地替换为真正的开始/触发节点（对齐 Dify start-placeholder panel）
   */
  function replaceStartPlaceholder(id, nextType) {
    if (store.readOnly) return null
    const nextData = getDefaultNodeData(nextType)
    const replacement = replaceStartPlaceholderInNodes({
      nodes: getNodes.value,
      id,
      nextType,
      nextData,
    })
    if (!replacement) return null
    recordHistory()
    setNodes(replacement.nodes)
    store.setSelectedNodeId(id)
    return replacement.node
  }

  // ---------------------------------------------------------------------------
  // 连线
  // ---------------------------------------------------------------------------
  /** 连线合法性校验（传给 <VueFlow :is-valid-connection>） */
  function isValidConnection(connection) {
    const { source, target } = connection
    if (!source || !target) return false
    if (source === target) return false // 禁止自环

    const sourceNode = findNode(source)
    const targetNode = findNode(target)
    if (!sourceNode || !targetNode) return false

    if (!canConnectAsSource(sourceNode.data?.type)) return false
    if (!canConnectAsTarget(targetNode.data?.type)) return false
    // Vue Flow also runs this during setEdges — allow same-id re-apply.
    if (shouldRejectDuplicateConnection(connection, getEdges.value)) return false

    // 容器边界：容器内部节点只能与同容器内部节点相连
    const sp = sourceNode.parentNode || sourceNode.parentId || null
    const tp = targetNode.parentNode || targetNode.parentId || null
    if (sp !== tp) return false

    if (wouldCreateCycle(getNodes.value, getEdges.value, connection)) return false

    return true
  }

  /** onConnect 回调：校验通过后建边 */
  function onConnect(connection, { record = true } = {}) {
    if (store.readOnly) return null
    if (!isValidConnection(connection)) return
    if (record) recordHistory()
    const sourceNode = findNode(connection.source)
    const targetNode = findNode(connection.target)
    const newEdge = {
      id: `${connection.source}-${connection.sourceHandle || DEFAULT_SOURCE_HANDLE}-${connection.target}-${connection.targetHandle || DEFAULT_TARGET_HANDLE}`,
      type: CUSTOM_EDGE,
      source: connection.source,
      target: connection.target,
      sourceHandle: connection.sourceHandle || DEFAULT_SOURCE_HANDLE,
      targetHandle: connection.targetHandle || DEFAULT_TARGET_HANDLE,
      data: {
        sourceType: sourceNode?.data?.type,
        targetType: targetNode?.data?.type,
      },
    }
    addEdges([newEdge])

    const sh = connection.sourceHandle || DEFAULT_SOURCE_HANDLE
    const th = connection.targetHandle || DEFAULT_TARGET_HANDLE
    if (sourceNode?.data) {
      const ids = new Set(sourceNode.data._connectedSourceHandleIds || [])
      ids.add(sh)
      vfUpdateNodeData(connection.source, { _connectedSourceHandleIds: [...ids] })
    }
    if (targetNode?.data) {
      const ids = new Set(targetNode.data._connectedTargetHandleIds || [])
      ids.add(th)
      vfUpdateNodeData(connection.target, { _connectedTargetHandleIds: [...ids] })
    }
    return newEdge
  }

  function addConnectedNode(type, { source, sourceHandle, position, data } = {}) {
    if (store.readOnly) return null
    if (!canConnectAsTarget(type)) return null
    const sourceNode = findNode(source)
    if (!sourceNode) return null

    const sourceParentId = sourceNode.parentNode || sourceNode.parentId
    const sourceParent = sourceParentId ? findNode(sourceParentId) : null

    recordHistory()
    const node = addNode(type, {
      position: position || getConnectedNodePosition(sourceNode, sourceParent),
      parentId: sourceParentId,
      connectionSourceId: source,
      data,
      record: false,
    })
    if (!node) return null

    const edge = onConnect({
      source,
      sourceHandle: sourceHandle || DEFAULT_SOURCE_HANDLE,
      target: node.id,
      targetHandle: DEFAULT_TARGET_HANDLE,
    }, { record: false })

    if (!edge) {
      removeNodes([node.id])
      return null
    }
    return node
  }

  function addPredecessorNode(type, { target, targetHandle, position, data } = {}) {
    if (store.readOnly || !canConnectAsSource(type)) return null
    const targetNode = findNode(target)
    if (!targetNode) return null

    const targetParentId = targetNode.parentNode || targetNode.parentId
    const targetParent = targetParentId ? findNode(targetParentId) : null

    recordHistory()
    const node = addNode(type, {
      position: position || getPredecessorNodePosition(targetNode, targetParent),
      parentId: targetParentId,
      connectionSourceId: '__predecessor__',
      data,
      record: false,
    })
    if (!node) return null

    const edge = onConnect({
      source: node.id,
      sourceHandle: DEFAULT_SOURCE_HANDLE,
      target,
      targetHandle: targetHandle || DEFAULT_TARGET_HANDLE,
    }, { record: false })

    if (!edge) {
      removeNodes([node.id])
      return null
    }
    return node
  }

  function insertNodeOnEdge(type, edgeId, { position, data } = {}) {
    if (store.readOnly) return null
    if (!canConnectAsTarget(type) || !canConnectAsSource(type)) return null
    const edge = getEdges.value.find((item) => item.id === edgeId)
    if (!edge) return null

    const sourceNode = findNode(edge.source)
    const targetNode = findNode(edge.target)
    if (!sourceNode || !targetNode) return null

    recordHistory()
    removeEdges([edgeId])
    const node = addNode(type, {
      position: position || {
        x: (sourceNode.position.x + targetNode.position.x) / 2,
        y: (sourceNode.position.y + targetNode.position.y) / 2,
      },
      parentId: sourceNode.parentNode || sourceNode.parentId,
      connectionSourceId: edge.source,
      data,
      record: false,
    })
    if (!node) return null

    onConnect({
      source: edge.source,
      sourceHandle: edge.sourceHandle || DEFAULT_SOURCE_HANDLE,
      target: node.id,
      targetHandle: DEFAULT_TARGET_HANDLE,
    }, { record: false })
    onConnect({
      source: node.id,
      sourceHandle: DEFAULT_SOURCE_HANDLE,
      target: edge.target,
      targetHandle: edge.targetHandle || DEFAULT_TARGET_HANDLE,
    }, { record: false })
    return node
  }

  // ---------------------------------------------------------------------------
  // 选中
  // ---------------------------------------------------------------------------
  function selectNode(id) {
    getNodes.value.forEach((n) => {
      n.selected = n.id === id
    })
    store.setSelectedNodeId(id)
  }

  function clearSelection() {
    getNodes.value.forEach((n) => {
      n.selected = false
    })
    store.setSelectedNodeId(null)
  }

  // ---------------------------------------------------------------------------
  // 复制 / 粘贴 / 克隆
  // ---------------------------------------------------------------------------
  function copySelection() {
    const selected = getSelectedNodes.value.filter((n) => (
      !isContainerStartNode(n.data?.type)
      && n.data?.type !== BlockEnum.LoopEnd
      && !isStartPlaceholderNode(n)
    ))
    if (selected.length === 0) return
    const ids = new Set(selected.map((n) => n.id))
    // 同时带上容器子节点
    getNodes.value.forEach((n) => {
      const pid = n.parentNode || n.parentId
      if (pid && ids.has(pid)) ids.add(n.id)
    })
    const nodes = getNodes.value.filter((n) => ids.has(n.id))
    const edges = getEdges.value.filter((e) => ids.has(e.source) && ids.has(e.target))
    store.setClipboard(flowToGraph(nodes, edges))
  }

  function copyNode(id) {
    const node = findNode(id)
    if (!node || isContainerStartNode(node.data?.type) || isStartPlaceholderNode(node)) return
    store.setClipboard(flowToGraph([node], []))
  }

  function paste() {
    if (store.readOnly) return
    if (!store.hasClipboard) return
    recordHistory()
    const clip = store.clipboard
    const idMap = new Map()
    const newFlowNodes = []
    const pasteableNodes = clip.nodes.filter(node => (
      node.data?.type !== BlockEnum.LoopEnd
      || canPasteLoopEnd(node, clip.nodes)
    ))

    // 先生成新 id
    pasteableNodes.forEach((n) => idMap.set(n.id, uid()))

    pasteableNodes.forEach((n) => {
      const { nodes: converted } = graphToFlow({ nodes: [n], edges: [] })
      const node = converted[0]
      node.id = idMap.get(n.id)
      node.position = { x: (n.position?.x || 0) + OFFSET, y: (n.position?.y || 0) + OFFSET }
      const pid = n.parentId || n.parentNode
      if (pid && idMap.has(pid)) {
        node.parentNode = idMap.get(pid)
        node.extent = 'parent'
      } else {
        delete node.parentNode
        delete node.extent
      }
      node.selected = true
      newFlowNodes.push(node)
    })

    const newEdges = clip.edges
      .filter((e) => idMap.has(e.source) && idMap.has(e.target))
      .map((e) => ({
        id: uid(),
        type: CUSTOM_EDGE,
        source: idMap.get(e.source),
        target: idMap.get(e.target),
        sourceHandle: e.sourceHandle || DEFAULT_SOURCE_HANDLE,
        targetHandle: e.targetHandle || DEFAULT_TARGET_HANDLE,
        data: { ...(e.data || {}) },
      }))

    clearSelection()
    addNodes(newFlowNodes)
    addEdges(newEdges)
  }

  function duplicateNode(id) {
    if (store.readOnly) return
    const node = findNode(id)
    if (!node || isContainerStartNode(node.data?.type) || node.data?.type === BlockEnum.LoopEnd || isStartPlaceholderNode(node)) return
    store.setClipboard(flowToGraph([node], []))
    paste()
  }

  function deleteSelected() {
    if (store.readOnly) return
    const selected = getSelectedNodes.value.filter((n) => !isContainerStartNode(n.data?.type))
    const selectedEdgeIds = getSelectedEdges.value.map(edge => edge.id)
    if (selected.length === 0 && selectedEdgeIds.length === 0) return
    // 容器一并删子节点
    const idsToRemove = new Set(selected.map((n) => n.id))
    getNodes.value.forEach((n) => {
      const pid = n.parentNode || n.parentId
      if (pid && idsToRemove.has(pid)) idsToRemove.add(n.id)
    })
    recordHistory()
    const ids = [...idsToRemove]
    const edgeIds = getEdges.value
      .filter((e) => idsToRemove.has(e.source) || idsToRemove.has(e.target))
      .map((e) => e.id)
    const allEdgeIds = [...new Set([...edgeIds, ...selectedEdgeIds])]
    if (allEdgeIds.length) removeEdges(allEdgeIds)
    if (ids.length) removeNodes(ids)
    if (store.selectedNodeId && idsToRemove.has(store.selectedNodeId)) store.setSelectedNodeId(null)
  }

  function organizeNodes() {
    if (store.readOnly) return
    const topLevelNodes = getNodes.value.filter((node) => !node.parentNode && !node.parentId)
    if (topLevelNodes.length < 2) return

    recordHistory()
    const ids = new Set(topLevelNodes.map((node) => node.id))
    const incoming = new Map(topLevelNodes.map((node) => [node.id, 0]))
    const outgoing = new Map(topLevelNodes.map((node) => [node.id, []]))
    for (const edge of getEdges.value) {
      if (!ids.has(edge.source) || !ids.has(edge.target))
        continue
      incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1)
      outgoing.get(edge.source).push(edge.target)
    }

    const levels = new Map()
    const queue = topLevelNodes
      .filter((node) => incoming.get(node.id) === 0)
      .map((node) => node.id)
    if (queue.length === 0)
      queue.push(topLevelNodes[0].id)

    for (const id of queue)
      levels.set(id, 0)
    while (queue.length) {
      const id = queue.shift()
      const nextLevel = (levels.get(id) || 0) + 1
      for (const target of outgoing.get(id) || []) {
        levels.set(target, Math.max(levels.get(target) || 0, nextLevel))
        incoming.set(target, incoming.get(target) - 1)
        if (incoming.get(target) === 0)
          queue.push(target)
      }
    }

    const rowsByLevel = new Map()
    for (const node of topLevelNodes) {
      const level = levels.get(node.id) || 0
      const row = rowsByLevel.get(level) || 0
      node.position = { x: 80 + level * 320, y: 80 + row * 180 }
      rowsByLevel.set(level, row + 1)
    }
  }

  // ---------------------------------------------------------------------------
  // 快捷键
  // ---------------------------------------------------------------------------
  function handleKeydown(e) {
    if (store.readOnly) return
    const tag = (e.target?.tagName || '').toLowerCase()
    const editing = tag === 'input' || tag === 'textarea' || e.target?.isContentEditable
    if (editing) return

    const mod = e.ctrlKey || e.metaKey
    if (mod && e.key.toLowerCase() === 'z' && !e.shiftKey) {
      e.preventDefault()
      undo()
    } else if (mod && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
      e.preventDefault()
      redo()
    } else if (mod && e.key.toLowerCase() === 'c') {
      copySelection()
    } else if (mod && e.key.toLowerCase() === 'v') {
      e.preventDefault()
      paste()
    } else if (mod && e.key.toLowerCase() === 'o') {
      e.preventDefault()
      organizeNodes()
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault()
      deleteSelected()
    }
  }

  function bindShortcuts() {
    window.addEventListener('keydown', handleKeydown)
  }
  function unbindShortcuts() {
    window.removeEventListener('keydown', handleKeydown)
  }

  if (options.autoBindShortcuts !== false) {
    onMounted(bindShortcuts)
    onUnmounted(unbindShortcuts)
  }

  return {
    // DSL
    initFromGraph,
    exportGraph,
    // 节点
    addNode,
    addConnectedNode,
    addPredecessorNode,
    insertNodeOnEdge,
    removeNode,
    updateNodeData,
    handleOutVarRenameChange,
    replaceStartPlaceholder,
    // 边
    onConnect,
    isValidConnection,
    removeEdge,
    // 选中
    selectNode,
    clearSelection,
    // 复制/粘贴/克隆/删除
    copySelection,
    copyNode,
    paste,
    duplicateNode,
    deleteSelected,
    organizeNodes,
    // 历史
    recordHistory,
    undo,
    redo,
    // 快捷键
    bindShortcuts,
    unbindShortcuts,
    // 透传 vue-flow 实例
    vueFlow: vf,
  }
}
