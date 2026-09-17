export const navigationItems = Object.freeze([
  Object.freeze({
    id: 'copilot',
    label: '工作流编排',
    to: '/',
  }),
  Object.freeze({
    id: 'integrations',
    label: '模型与工具',
    to: '/integrations',
  }),
  Object.freeze({
    id: 'knowledge',
    label: '知识库',
    to: '/datasets',
  }),
])

export function resolveActiveNavigation(path) {
  if (path.startsWith('/integrations'))
    return 'integrations'
  if (path.startsWith('/datasets'))
    return 'knowledge'
  return 'copilot'
}
