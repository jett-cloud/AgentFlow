export const NOTE_THEMES = Object.freeze([
  'blue',
  'cyan',
  'green',
  'yellow',
  'pink',
  'violet',
])

export const NOTE_MIN_WIDTH = 240
export const NOTE_MIN_HEIGHT = 88

export const NOTE_DEFAULTS = Object.freeze({
  title: '',
  desc: '',
  text: '',
  theme: 'blue',
  author: '我',
  showAuthor: true,
  width: NOTE_MIN_WIDTH,
  height: NOTE_MIN_HEIGHT,
})

function readLexicalNodeText(node) {
  if (!node || typeof node !== 'object') return ''
  if (typeof node.text === 'string') return node.text
  if (node.type === 'linebreak') return '\n'
  if (!Array.isArray(node.children)) return ''
  return node.children.map(readLexicalNodeText).join('')
}

export function noteTextToPlainText(value = '') {
  if (typeof value !== 'string' || !value) return ''

  try {
    const state = JSON.parse(value)
    if (!state?.root || state.root.type !== 'root' || !Array.isArray(state.root.children))
      return value
    return state.root.children.map(readLexicalNodeText).join('\n')
  }
  catch {
    return value
  }
}

function createLexicalTextNode(text) {
  return {
    detail: 0,
    format: 0,
    mode: 'normal',
    style: '',
    text,
    type: 'text',
    version: 1,
  }
}

function createLexicalParagraph(text) {
  return {
    children: text ? [createLexicalTextNode(text)] : [],
    direction: 'ltr',
    format: '',
    indent: 0,
    type: 'paragraph',
    version: 1,
    textFormat: 0,
    textStyle: '',
  }
}

export function plainTextToNoteEditorState(value = '') {
  const text = String(value ?? '')
  if (!text) return ''

  return JSON.stringify({
    root: {
      children: text.split(/\r?\n/).map(createLexicalParagraph),
      direction: 'ltr',
      format: '',
      indent: 0,
      type: 'root',
      version: 1,
      textFormat: 0,
      textStyle: '',
    },
  })
}

function normalizeSize(value, minimum) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.max(minimum, Math.round(numeric)) : minimum
}

export function normalizeNoteData(data = {}) {
  return {
    ...NOTE_DEFAULTS,
    ...data,
    theme: NOTE_THEMES.includes(data.theme) ? data.theme : NOTE_DEFAULTS.theme,
    width: normalizeSize(data.width, NOTE_MIN_WIDTH),
    height: normalizeSize(data.height, NOTE_MIN_HEIGHT),
  }
}

export function getResizedNoteSize({
  width,
  height,
  deltaX = 0,
  deltaY = 0,
  zoom = 1,
} = {}) {
  const safeZoom = Number.isFinite(Number(zoom)) && Number(zoom) > 0 ? Number(zoom) : 1
  return {
    width: normalizeSize(Number(width) + Number(deltaX) / safeZoom, NOTE_MIN_WIDTH),
    height: normalizeSize(Number(height) + Number(deltaY) / safeZoom, NOTE_MIN_HEIGHT),
  }
}
