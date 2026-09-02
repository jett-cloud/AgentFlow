import { localizeToolText } from './toolProviderHelpers.js'

export function buildToolDetails(tools) {
  return (Array.isArray(tools) ? tools : []).map((tool, index) => {
    const toolId = tool.name || tool.tool_name || 'tool'
    return {
      key: `${toolId}:${index}`,
      name: localizeToolText(tool.label, toolId),
      description: localizeToolText(tool.description, '暂无详细描述'),
    }
  })
}
