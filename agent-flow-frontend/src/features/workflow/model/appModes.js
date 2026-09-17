/**
 * App mode constants aligned with Dify AppModeEnum
 * (web/types/app.ts + create-app-modal).
 */

export const AppMode = {
  WORKFLOW: 'workflow',
  ADVANCED_CHAT: 'advanced-chat',
  CHAT: 'chat',
  AGENT_CHAT: 'agent-chat',
  COMPLETION: 'completion',
}

/** List filter: omit API `mode` when ALL (same as Dify apps/list.tsx). */
export const AppListCategory = {
  ALL: 'all',
  WORKFLOW: AppMode.WORKFLOW,
  CHATFLOW: AppMode.ADVANCED_CHAT,
  CHAT: AppMode.CHAT,
  AGENT: AppMode.AGENT_CHAT,
  COMPLETION: AppMode.COMPLETION,
}

export const AppListSortBy = {
  LAST_MODIFIED: 'last_modified',
  RECENTLY_CREATED: 'recently_created',
  EARLIEST_CREATED: 'earliest_created',
}

export function isChatflowMode(mode) {
  return mode === AppMode.ADVANCED_CHAT
}

export function isWorkflowStudioMode(mode) {
  return mode === AppMode.WORKFLOW || mode === AppMode.ADVANCED_CHAT
}

export function appModeLabel(mode) {
  if (isChatflowMode(mode))
    return 'Chatflow'
  if (mode === AppMode.WORKFLOW)
    return '工作流'
  if (mode === AppMode.CHAT)
    return '聊天助手'
  if (mode === AppMode.AGENT_CHAT)
    return 'Agent'
  if (mode === AppMode.COMPLETION)
    return '文本生成'
  return mode || ''
}

/** Header run button: Dify RunMode vs PreviewMode labels. */
export function debugActionLabel(mode, { isRunning = false } = {}) {
  if (isRunning)
    return '运行中…'
  return isChatflowMode(mode) ? '调试与预览' : '测试运行'
}
