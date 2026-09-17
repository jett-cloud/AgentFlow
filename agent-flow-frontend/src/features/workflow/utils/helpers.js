/**
 * CoPilot 模块的辅助渲染与格式化函数
 */

import {
  isThinkBlockComplete,
  preprocessThinkTag,
  renderThinkBlockHtml,
  splitThinkSegments,
  stripEndThinkFlag,
} from '../runtime/markdownThink.js'
import { extractMathSlots, restoreMathSlots } from './markdownMath.js'

export const getNoteText = (text) => {
  if (!text) return ''
  try {
    const parsed = JSON.parse(text)
    if (parsed && parsed.root) {
      const extractText = (node) => {
        if (!node) return ''
        if (node.text) return node.text
        if (node.children) {
          return node.children.map(extractText).join('\n')
        }
        return ''
      }
      return extractText(parsed.root)
    }
  } catch (e) {
    // If it's not JSON, return as is
  }
  return text
}

export const getToolIcon = (toolName) => {
  if (!toolName) return '⚙️'
  if (toolName.includes('Weather') || toolName.includes('weather')) return '☀️'
  if (toolName.includes('DingTalk') || toolName.includes('ding')) return '🔔'
  if (toolName.includes('http') || toolName.includes('HTTP')) return '🌐'
  if (toolName.includes('Email')) return '✉️'
  if (toolName.includes('jina') || toolName.includes('Jina')) return '🌐'
  return '⚙️'
}

export const getToolParametersToDisplay = (data) => {
  if (!data) return []
  const params = []

  const extractValue = (param) => {
    if (param == null) return ''
    if (typeof param === 'string' || typeof param === 'number' || typeof param === 'boolean') {
      return String(param)
    }
    if (param.value !== undefined && param.value !== null) return param.value
    if (param.variable !== undefined) return param.variable
    return ''
  }

  // 1. Dify style tool_parameters
  if (data.tool_parameters) {
    Object.entries(data.tool_parameters).forEach(([key, param]) => {
      params.push({
        name: key.toUpperCase(),
        value: extractValue(param)
      })
    })
  }

  // 2. Dify style tool_configurations
  if (data.tool_configurations) {
    Object.entries(data.tool_configurations).forEach(([key, param]) => {
      params.push({
        name: key.toUpperCase(),
        value: extractValue(param)
      })
    })
  }

  // 3. Native AgentFlow style args
  if (data.args && params.length === 0) {
    Object.entries(data.args).forEach(([key, value]) => {
      params.push({
        name: key.toUpperCase(),
        value: value !== undefined && value !== null ? value : ''
      })
    })
  }

  return params
}

export const isToolConfigured = (toolName, toolsList) => {
  if (!toolName || !toolsList) return true
  const tool = toolsList.find(t => t.name === toolName)
  if (tool) {
    return tool.configured !== false
  }
  return true
}

export const getBadgeType = (status) => {
  if (!status) return 'info'
  switch (status) {
    case 'SUCCESS': return 'success'
    case 'FAILED': return 'danger'
    case 'RUNNING':
    case 'RETRYING': return 'primary'
    case 'WAITING_APPROVAL': return 'warning'
    default: return 'info'
  }
}

export const getStepTimelineStatus = (status) => {
  switch (status) {
    case 'SUCCESS': return 'success'
    case 'FAILED': return 'error'
    case 'RUNNING':
    case 'RETRYING': return 'process'
    default: return 'wait'
  }
}

export const formatJson = (val) => {
  if (!val) return '{}'
  try {
    return JSON.stringify(val, null, 2)
  } catch (e) {
    return val
  }
}

export const renderMarkdown = (text, options = {}) => {
  if (!text)
    return '暂无输出'

  const { isResponding = false } = options
  return renderMarkdownWithThink(String(text), { isResponding })
}

function renderMarkdownWithThink(text, { isResponding = false } = {}) {
  const segments = splitThinkSegments(preprocessThinkTag(text))
  if (!segments.length)
    return renderMarkdownFragment(text)

  return segments.map((segment) => {
    if (segment.type !== 'think')
      return renderMarkdownFragment(segment.text)

    const { body, hasEndFlag } = stripEndThinkFlag(segment.text)
    const isComplete = isThinkBlockComplete({
      complete: segment.complete,
      hasEndFlag,
      isResponding,
    })
    return renderThinkBlockHtml({
      bodyHtml: renderMarkdownFragment(body),
      isComplete,
    })
  }).join('')
}

function safeMarkdownHref(value) {
  const href = String(value || '').trim()
  if (!href || /[\u0000-\u001F\u007F"'`\\]/.test(href) || /&(?:#\d+|#x[\da-f]+|colon);/i.test(href))
    return ''
  if (/^https?:\/\//i.test(href))
    return href
  if (/^(?:\/(?!\/)|\.\.?\/|#)/.test(href))
    return href
  if (!/^[a-z][a-z\d+.-]*:/i.test(href) && !href.startsWith('//'))
    return href
  return ''
}

function escapeHtmlAttribute(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function renderMarkdownFragment(text) {
  if (!text)
    return ''

  const { text: withMathPlaceholders, slots: mathSlots } = extractMathSlots(String(text))

  // Escape HTML first so v-html stays safe for untrusted model output.
  let html = withMathPlaceholders
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Fenced code blocks (before inline formatting).
  const codeBlocks = []
  html = html.replace(/```([\w+-]*)\n?([\s\S]*?)```/g, (_match, lang, code) => {
    const index = codeBlocks.length
    const body = String(code || '').replace(/\n$/, '')
    if (String(lang || '').toLowerCase() === 'mermaid') {
      codeBlocks.push(`<pre class="mermaid">${body}</pre>`)
    }
    else {
      codeBlocks.push(`<pre class="markdown-code-block"><code>${body}</code></pre>`)
    }
    return `\u0000CODE${index}\u0000`
  })

  // Keep inline code out of all later emphasis/link substitutions.
  const inlineCodes = []
  html = html.replace(/`([^`]+)`/g, (_match, code) => {
    const index = inlineCodes.length
    inlineCodes.push(`<code class="markdown-inline-code">${code}</code>`)
    return `\u0000INLINECODE${index}\u0000`
  })

  // Bold: **text** or __text__
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(?<![\p{L}\p{N}_])__([^_]+)__(?![\p{L}\p{N}_])/gu, '<strong>$1</strong>')

  // Italic: *text* or _text_
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>')
  html = html.replace(/(?<![\p{L}\p{N}_])_([^_]+)_(?![\p{L}\p{N}_])/gu, '<em>$1</em>')

  // Links: [text](url)
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, p1, p2) => {
    const href = safeMarkdownHref(p2.replace(/&amp;/g, '&'))
    if (!href)
      return p1
    return `<a href="${escapeHtmlAttribute(href)}" target="_blank" rel="noopener noreferrer" class="markdown-link">${p1}</a>`
  })

  // Split lines to process lists / headings
  const lines = html.split('\n')
  const resultLines = []
  let listType = null // 'ul', 'ol', or null

  const closeList = () => {
    if (!listType)
      return
    resultLines.push(listType === 'ul' ? '</ul>' : '</ol>')
    listType = null
  }

  for (const line of lines) {
    const trimmed = line.trim()

    // Headings: # .. ######
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/)
    if (headingMatch) {
      closeList()
      const level = headingMatch[1].length
      resultLines.push(`<h${level} class="markdown-heading">${headingMatch[2]}</h${level}>`)
      continue
    }

    // Unordered list: starts with "- " or "* "
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      if (listType !== 'ul') {
        closeList()
        listType = 'ul'
        resultLines.push('<ul class="markdown-list">')
      }
      const content = line.replace(/^\s*[-*]\s+/, '')
      resultLines.push(`<li>${content}</li>`)
      continue
    }

    // Ordered list: starts with "数字. "
    if (/^\d+\.\s+/.test(trimmed)) {
      if (listType !== 'ol') {
        closeList()
        listType = 'ol'
        resultLines.push('<ol class="markdown-list">')
      }
      const content = line.replace(/^\s*\d+\.\s+/, '')
      resultLines.push(`<li>${content}</li>`)
      continue
    }

    closeList()
    resultLines.push(line)
  }

  closeList()

  const isStructural = (line) => (
    line === '<ul class="markdown-list">'
    || line === '</ul>'
    || line === '<ol class="markdown-list">'
    || line === '</ol>'
    || line.startsWith('<li>')
    || line.startsWith('<h')
    || line.startsWith('<pre')
  )

  let finalHtml = ''
  for (let i = 0; i < resultLines.length; i++) {
    const line = resultLines[i]
    if (isStructural(line)) {
      finalHtml += line
      continue
    }
    const next = resultLines[i + 1]
    const needsBreak = i < resultLines.length - 1 && next != null && !isStructural(next)
    finalHtml += line + (needsBreak ? '<br/>' : '')
  }

  // Restore fenced code blocks
  finalHtml = finalHtml.replace(/\u0000CODE(\d+)\u0000/g, (_m, index) => codeBlocks[Number(index)] || '')
  finalHtml = finalHtml.replace(/\u0000INLINECODE(\d+)\u0000/g, (_m, index) => inlineCodes[Number(index)] || '')

  // Restore KaTeX (trusted HTML from katex.renderToString)
  return restoreMathSlots(finalHtml, mathSlots)
}

export const getNodeIconStyle = (step) => {
  if (step.toolName === 'start' || step.stepId.toLowerCase().includes('start')) {
    return { backgroundColor: '#eff6ff', color: '#1d4ed8' }
  } else if (step.toolName === 'LLM_TASK' || step.toolName === 'llm') {
    return { backgroundColor: '#f5f3ff', color: '#6d28d9' }
  } else if (step.toolName === 'approval' || step.toolName === 'approval_task') {
    return { backgroundColor: '#ecfeff', color: '#0e7490' }
  } else {
    return { backgroundColor: '#fff7ed', color: '#c2410c' }
  }
}

export const getNodeIconText = (step) => {
  if (step.toolName === 'start' || step.stepId.toLowerCase().includes('start')) {
    return '👤'
  } else if (step.toolName === 'LLM_TASK' || step.toolName === 'llm') {
    return '🧠'
  } else if (step.toolName === 'approval' || step.toolName === 'approval_task') {
    return '👋'
  } else {
    return '🏁'
  }
}

export const getTokenCountForStep = (step) => {
  const promptLen = step.promptText ? step.promptText.length : 0
  const outputLen = step.output ? step.output.length : 0
  const tokens = Math.round((promptLen + outputLen) * 0.75 + 100)
  if (tokens >= 1000) {
    return (tokens / 1000).toFixed(3) + 'K'
  }
  return tokens
}

export const formatDateTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    const pad = (num) => String(num).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch (e) {
    return dateStr
  }
}

export const formatSessionTime = (timeStr) => {
  if (!timeStr) return ''
  try {
    const d = new Date(timeStr)
    if (isNaN(d.getTime())) return timeStr
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 1) return '刚刚'
    if (diffMins < 60) return `${diffMins}分钟前`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}小时前`
    const pad = (num) => String(num).padStart(2, '0')
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch (e) {
    return timeStr
  }
}

export const getVarTypeIcon = (type) => {
  const map = {
    'text-input': '📝',
    'paragraph': '📄',
    'select': '🔽',
    'number': '🔢',
    'file': '📁',
    'file-list': '📁',
    'image': '🖼️'
  }
  return map[type] || '📝'
}
