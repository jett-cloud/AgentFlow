const STRING_OPERATORS = [
  'is',
  'is not',
  'contains',
  'not contains',
  'start with',
  'end with',
  'empty',
  'not empty',
  'in',
  'not in',
]

const NUMBER_OPERATORS = ['=', '≠', '>', '<', '≥', '≤', 'empty', 'not empty']

const TIME_OPERATORS = ['is', 'before', 'after', 'empty', 'not empty']

const EMPTY_OPERATORS = new Set([
  'empty',
  'not empty',
  'is null',
  'is not null',
  'exists',
  'not exists',
])

export const METADATA_TYPES = [
  { value: 'string', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'time', label: '时间' },
]

export function metadataNameError(name) {
  const value = String(name || '')
  if (!value)
    return '请输入字段名'
  if (!/^[a-z][a-z0-9_]*$/.test(value))
    return '字段名须以小写字母开头，仅含小写字母、数字和下划线'
  if (value.length > 255)
    return '字段名不能超过 255 个字符'
  return ''
}

export function operatorsForMetadataType(type) {
  if (type === 'number')
    return [...NUMBER_OPERATORS]
  if (type === 'time')
    return [...TIME_OPERATORS]
  return [...STRING_OPERATORS]
}

export function defaultOperatorForType(type) {
  return type === 'number' ? '=' : 'is'
}

export function operatorRequiresValue(operator) {
  return !EMPTY_OPERATORS.has(String(operator || ''))
}

export function intersectMetadataByName(lists) {
  const arrays = (Array.isArray(lists) ? lists : []).map(list => (Array.isArray(list) ? list : []))
  if (!arrays.length)
    return []
  const [first, ...rest] = arrays
  if (!rest.length)
    return [...first]
  return first.filter(item => rest.every(list => list.some(other => other.name === item.name)))
}

export function mergeDocumentMetadataForBatch(documents) {
  const fields = new Map()
  for (const document of Array.isArray(documents) ? documents : []) {
    for (const item of document?.doc_metadata || []) {
      if (!item?.id || item.id === 'built-in')
        continue
      const existing = fields.get(item.id)
      if (!existing) {
        fields.set(item.id, {
          id: item.id,
          name: item.name,
          type: item.type,
          value: item.value ?? null,
          isMultipleValue: false,
        })
        continue
      }
      if (String(existing.value ?? '') !== String(item.value ?? '')) {
        existing.isMultipleValue = true
        existing.value = null
      }
    }
  }
  return [...fields.values()]
}

export function buildDocumentsMetadataBody(documentIds, metadataList) {
  const list = (Array.isArray(metadataList) ? metadataList : []).map(item => ({
    id: item.id,
    name: item.name,
    value: item.value ?? null,
  }))
  return {
    operation_data: (Array.isArray(documentIds) ? documentIds : []).map(documentId => ({
      document_id: documentId,
      metadata_list: list,
      partial_update: true,
    })),
  }
}

export function fieldForCondition(condition, metadataList) {
  const list = Array.isArray(metadataList) ? metadataList : []
  if (condition?.metadata_id) {
    const byIdAndName = list.find(item =>
      item.id === condition.metadata_id && item.name === condition.name,
    )
    if (byIdAndName)
      return byIdAndName
    const byId = list.filter(item => item.id === condition.metadata_id)
    if (byId.length === 1)
      return byId[0]
  }
  return list.find(item => item.name === condition?.name) || null
}
