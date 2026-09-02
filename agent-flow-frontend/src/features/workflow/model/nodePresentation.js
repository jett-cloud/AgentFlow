const TYPE_ALIASES = Object.freeze({
  'agent-v2': 'agent',
  assigner: 'variable-assigner',
  'custom-iteration-start': 'iteration-start',
  'custom-loop-start': 'loop-start',
})

const ENTRY_LABELS = Object.freeze({
  start: 'START',
  'start-placeholder': 'START',
  datasource: 'DATA SOURCE',
  'trigger-schedule': 'TRIGGER',
  'trigger-webhook': 'TRIGGER',
  'trigger-plugin': 'TRIGGER',
})

const TERMINAL_TYPES = new Set(['answer', 'end', 'loop-end'])
const BRANCH_TYPES = new Set(['if-else', 'question-classifier', 'human-input'])
const CONTAINER_TYPES = new Set(['iteration', 'loop'])
const ANNOTATION_TYPES = new Set(['note'])

export function normalizePresentationType(type) {
  return TYPE_ALIASES[type] || type || 'default'
}

export function getEntryLabel(type) {
  return ENTRY_LABELS[normalizePresentationType(type)] || ''
}

export function getNodePresentation(type) {
  const normalizedType = normalizePresentationType(type)

  if (ANNOTATION_TYPES.has(normalizedType)) {
    return {
      kind: 'annotation',
      showEntryShell: false,
      showTargetHandle: false,
      showSourceHandle: false,
      sourceHandleMode: 'none',
    }
  }

  if (normalizedType === 'start-placeholder') {
    return {
      kind: 'entry',
      showEntryShell: true,
      showTargetHandle: false,
      showSourceHandle: false,
      sourceHandleMode: 'none',
    }
  }

  if (normalizedType === 'iteration-start' || normalizedType === 'loop-start') {
    return {
      kind: 'internal-start',
      showEntryShell: false,
      showTargetHandle: false,
      showSourceHandle: true,
      sourceHandleMode: 'header',
    }
  }

  if (ENTRY_LABELS[normalizedType]) {
    return {
      kind: 'entry',
      showEntryShell: true,
      showTargetHandle: false,
      showSourceHandle: true,
      sourceHandleMode: 'header',
    }
  }

  if (TERMINAL_TYPES.has(normalizedType)) {
    return {
      kind: 'terminal',
      showEntryShell: false,
      showTargetHandle: true,
      showSourceHandle: false,
      sourceHandleMode: 'none',
    }
  }

  if (BRANCH_TYPES.has(normalizedType)) {
    return {
      kind: 'branch',
      showEntryShell: false,
      showTargetHandle: true,
      showSourceHandle: false,
      sourceHandleMode: 'rows',
    }
  }

  if (CONTAINER_TYPES.has(normalizedType)) {
    return {
      kind: 'container',
      showEntryShell: false,
      showTargetHandle: true,
      showSourceHandle: true,
      sourceHandleMode: 'header',
    }
  }

  return {
    kind: 'standard',
    showEntryShell: false,
    showTargetHandle: true,
    showSourceHandle: true,
    sourceHandleMode: 'header',
  }
}
