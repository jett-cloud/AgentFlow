// src/stores/useWorkflowStore.js
//
// 工作流画布的中央状态（Pinia）。
// 注意：live 的 nodes/edges 由 vue-flow 持有（性能/交互原因），
// 这里只保存“跨组件共享 + 需要持久化”的状态：选中项、历史快照、剪贴板、元信息。
// 历史快照通过 useWorkflowCore.js 在每次结构性变更后写入。

import { defineStore } from 'pinia'
import { normalizeRagPipelineVariables } from '@/features/workflow/model/objectChildTree.js'

const MAX_HISTORY = 50

function clone(obj) {
  return JSON.parse(JSON.stringify(obj))
}

export const useWorkflowStore = defineStore('workflow', {
  state: () => ({
    /** 当前工作流元信息 */
    workflowId: null,
    workflowName: '未命名工作流',
    readOnly: false,

    /** 当前选中的节点 id（右侧面板据此渲染） */
    selectedNodeId: null,

    /** 工作流级变量。后端接入后分别映射 environment_variables / conversation_variables。 */
    environmentVariables: [],
    conversationVariables: [],
    /** RAG pipeline variables（知识库流水线 shared / 节点级输入） */
    ragPipelineVariables: [],

    /** 复制/剪切缓冲：{ nodes: [], edges: [] } */
    clipboard: null,

    /** 撤销/重做历史：past 为已发生的历史，future 为被撤销可重做的 */
    past: [],
    future: [],

    /** 运行态（后续对接执行引擎 SSE 时用） */
    isRunning: false,
  }),

  getters: {
    canUndo: (state) => state.past.length > 0,
    canRedo: (state) => state.future.length > 0,
    hasClipboard: (state) => !!state.clipboard && (state.clipboard.nodes?.length > 0),
  },

  actions: {
    setMeta({ workflowId, workflowName, readOnly } = {}) {
      if (workflowId !== undefined) this.workflowId = workflowId
      if (workflowName !== undefined) this.workflowName = workflowName
      if (readOnly !== undefined) this.readOnly = readOnly
    },

    setSelectedNodeId(id) {
      this.selectedNodeId = id
    },

    setEnvironmentVariables(variables) {
      this.environmentVariables = clone(variables || [])
    },

    setConversationVariables(variables) {
      this.conversationVariables = clone(variables || [])
    },

    setRagPipelineVariables(variables) {
      this.ragPipelineVariables = clone(normalizeRagPipelineVariables(variables))
    },

    setClipboard(payload) {
      this.clipboard = payload ? clone(payload) : null
    },

    /**
     * 记录一次历史快照。调用方在“变更前”把旧的 { nodes, edges } 传进来。
     * 一旦记录新历史，future（重做栈）清空。
     */
    record(snapshot) {
      this.past.push(clone(snapshot))
      if (this.past.length > MAX_HISTORY) this.past.shift()
      this.future = []
    },

    /**
     * 撤销：把“当前状态”传进来以便放入 future，返回要恢复的上一个快照。
     * @returns {object|null} 上一个 { nodes, edges }，无则 null
     */
    undo(currentSnapshot) {
      if (this.past.length === 0) return null
      const prev = this.past.pop()
      this.future.push(clone(currentSnapshot))
      return prev
    },

    /**
     * 重做：返回要恢复的下一个快照，并把“当前状态”放回 past。
     */
    redo(currentSnapshot) {
      if (this.future.length === 0) return null
      const next = this.future.pop()
      this.past.push(clone(currentSnapshot))
      return next
    },

    resetHistory() {
      this.past = []
      this.future = []
    },

    setRunning(v) {
      this.isRunning = !!v
    },
  },
})
