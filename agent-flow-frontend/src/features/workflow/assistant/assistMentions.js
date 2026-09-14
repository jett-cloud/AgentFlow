export const ASSIST_MENTION_LIMIT = 8

const GROUP_ORDER = ['node', 'tool', 'dataset']

export function detectMentionTrigger(textBeforeCaret) {
  const text = String(textBeforeCaret || '')
  const match = text.match(/(^|[\s])@([^\s@]*)$/)
  if (!match)
    return null
  return {
    query: match[2],
    start: text.length - match[2].length - 1,
  }
}

export function catalogMentionItems({ nodes = [], tools = [], datasets = [] } = {}) {
  return [
    ...nodes.flatMap((node) => {
      const id = String(node?.id || '')
      if (!id)
        return []
      const data = node.data && typeof node.data === 'object' ? node.data : {}
      return [{
        kind: 'node',
        id,
        label: String(data.title || data.type || id),
      }]
    }),
    ...tools.flatMap((tool) => {
      const provider = String(tool?.provider_catalogue_name || tool?.provider_id || tool?.provider_name || '').trim()
      const toolName = String(tool?.tool_name || '').trim()
      if (!provider || !toolName)
        return []
      return [{
        kind: 'tool',
        id: `${provider}/${toolName}`,
        label: String(tool.tool_label || tool.label || toolName),
        provider,
        tool_name: toolName,
      }]
    }),
    ...datasets.flatMap((dataset) => {
      const id = String(dataset?.id || '')
      if (!id)
        return []
      return [{
        kind: 'dataset',
        id,
        label: String(dataset.name || dataset.label || id),
      }]
    }),
  ]
}

export function insertSelectedNodeMentions({ nodes = [], nodeIds = [], insertResource } = {}) {
  if (typeof insertResource !== 'function')
    return false
  const nodesById = new Map(nodes.map(node => [String(node?.id || ''), node]))
  const selectedNodes = [...new Set(nodeIds.map(String))]
    .map(id => nodesById.get(id))
    .filter(Boolean)
  const mentions = catalogMentionItems({ nodes: selectedNodes })
  for (const mention of mentions)
    insertResource(mention)
  return mentions.length > 0
}

export function filterMentionGroups(items, query) {
  const needle = String(query || '').trim().toLowerCase()
  const grouped = Object.fromEntries(GROUP_ORDER.map(kind => [kind, []]))
  for (const item of Array.isArray(items) ? items : []) {
    if (!GROUP_ORDER.includes(item?.kind))
      continue
    if (needle && !mentionHaystack(item).includes(needle))
      continue
    grouped[item.kind].push(item)
  }
  return GROUP_ORDER.map(kind => ({ kind, items: grouped[kind] }))
}

export function serializeMentionReferences(chips, catalog = []) {
  const references = []
  const seen = new Set()
  for (const chip of Array.isArray(chips) ? chips : []) {
    if (references.length >= ASSIST_MENTION_LIMIT)
      break
    const reference = refreshToolReference(referenceFromChip(chip), catalog)
    if (!reference)
      continue
    const key = `${reference.kind}:${reference.id}`
    if (seen.has(key))
      continue
    seen.add(key)
    references.push(reference)
  }
  return references
}

function refreshToolReference(reference, catalog) {
  if (reference?.kind !== 'tool')
    return reference
  const matches = (Array.isArray(catalog) ? catalog : []).filter(item => (
    item?.kind === 'tool'
    && item?.tool_name === reference.tool_name
  ))
  const match = matches.find(item => item.id === reference.id)
    || (matches.length === 1 ? matches[0] : null)
  if (!match?.id || !match?.provider || !match?.tool_name)
    return reference
  return {
    kind: 'tool',
    id: match.id,
    label: match.label || reference.label,
    provider: match.provider,
    tool_name: match.tool_name,
  }
}

export function splitTextByMentions(text, references) {
  const source = String(text || '')
  const candidates = Array.isArray(references) ? references : []
  const parts = []
  let cursor = 0
  while (cursor < source.length) {
    let nextIndex = -1
    let nextReference = null
    for (const reference of candidates) {
      const label = String(reference?.label || '')
      if (!label)
        continue
      const index = source.indexOf(label, cursor)
      if (index < 0)
        continue
      if (nextIndex < 0 || index < nextIndex) {
        nextIndex = index
        nextReference = reference
      }
    }
    if (!nextReference) {
      parts.push({ text: source.slice(cursor) })
      break
    }
    if (nextIndex > cursor)
      parts.push({ text: source.slice(cursor, nextIndex) })
    parts.push({ text: nextReference.label, reference: nextReference })
    cursor = nextIndex + String(nextReference.label).length
  }
  return parts.filter(part => part.text)
}

export function mentionChipAttributes(item) {
  if (!item?.kind || !item?.id)
    return null
  const attrs = {
    contenteditable: 'false',
    'data-resource-reference': 'true',
    'data-assist-mention': 'true',
    'data-kind': item.kind,
    'data-id': item.id,
  }
  if (item.kind === 'tool') {
    attrs['data-provider'] = item.provider || ''
    attrs['data-tool-name'] = item.tool_name || ''
  }
  return attrs
}

function mentionHaystack(item) {
  return [item.label, item.id, item.provider, item.tool_name]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function referenceFromChip(chip) {
  const dataset = chip?.dataset || {}
  const kind = String(dataset.kind || '')
  const id = String(dataset.id || '')
  const label = String(chip?.textContent || '').trim()
  if (!id || !['node', 'tool', 'dataset'].includes(kind))
    return null
  if (kind === 'tool') {
    const provider = String(dataset.provider || '')
    const toolName = String(dataset.toolName || dataset.tool_name || '')
    if (!provider || !toolName)
      return null
    return { kind, id, label: label || id, provider, tool_name: toolName }
  }
  return { kind, id, label: label || id }
}
