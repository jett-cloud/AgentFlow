import { load as loadYaml } from 'js-yaml'
import { sanitizePluginIdSegment, sanitizeToolIdentityName } from './pluginIdentityHelpers.js'

function providerYamlPaths(files) {
  return Object.keys(files || {})
    .filter(path => path.startsWith('provider/') && (path.endsWith('.yaml') || path.endsWith('.yml')))
    .sort()
}

function isSafeIdentityStem(stem) {
  return Boolean(stem) && stem !== '__init__' && !stem.includes('.')
}

function toolYamlPaths(files) {
  return Object.keys(files || {})
    .filter(path => path.startsWith('tools/') && (path.endsWith('.yaml') || path.endsWith('.yml')))
    .sort()
}

export function extractCredentialsSchemaFromFiles(files = {}) {
  for (const path of providerYamlPaths(files)) {
    try {
      const doc = loadYaml(files[path]) || {}
      const raw = doc.credentials_for_provider
      if (!raw || typeof raw !== 'object')
        continue
      const schema = []
      for (const [name, spec] of Object.entries(raw)) {
        if (!name)
          continue
        const entry = typeof spec === 'object' && spec
          ? { name, type: 'secret-input', required: true, ...spec }
          : { name, type: 'secret-input', required: true }
        entry.name = name
        if (!entry.type)
          entry.type = 'secret-input'
        if (entry.required === undefined)
          entry.required = true
        schema.push(entry)
      }
      if (schema.length)
        return schema
    }
    catch {
      // ignore invalid yaml
    }
  }
  return []
}

export function extractProviderIdentityName(files = {}, fallback = '') {
  for (const path of providerYamlPaths(files)) {
    try {
      const doc = loadYaml(files[path]) || {}
      const name = doc?.identity?.name
      if (name) {
        const sanitized = sanitizePluginIdSegment(name)
        if (sanitized)
          return sanitized
      }
      const stem = path.replace(/^provider\//, '').replace(/\.ya?ml$/, '')
      if (isSafeIdentityStem(stem)) {
        const sanitized = sanitizePluginIdSegment(stem)
        if (sanitized)
          return sanitized
      }
    }
    catch {
      // ignore
    }
  }
  return sanitizePluginIdSegment(fallback) || fallback
}

/** Dify expects org/plugin/provider (3 segments). Upgrade legacy org/plugin and sanitize segments. */
export function normalizePluginProviderId(providerId, { providerName } = {}) {
  const value = String(providerId || '').trim()
  if (!value)
    return value
  const parts = value.split('/')
  if (parts.length === 3) {
    const [org, plugin, provider] = parts.map(sanitizePluginIdSegment)
    if (!org || !plugin || !provider)
      return value
    return `${org}/${plugin}/${provider}`
  }
  if (parts.length === 2) {
    const org = sanitizePluginIdSegment(parts[0])
    const plugin = sanitizePluginIdSegment(parts[1])
    const provider = sanitizePluginIdSegment(providerName || plugin)
    if (!org || !plugin || !provider)
      return value
    return `${org}/${plugin}/${provider}`
  }
  return value
}

/**
 * Ensure preview_tool carries credentials_schema / parameters from current workspace files.
 * Fixes stale session preview_tool saved before credentials_schema existed.
 */
export function enrichPreviewToolFromFiles(previewTool, files = {}, { toolName } = {}) {
  if (!previewTool && !Object.keys(files || {}).length)
    return null

  const credentialsSchema = extractCredentialsSchemaFromFiles(files)
  const providerIdentityName = extractProviderIdentityName(files, '')
  const base = previewTool ? { ...previewTool } : {}
  const activeTool = toolName || base.tool_name

  // Prefer parameters from the selected tool yaml when available.
  let parametersSchema = Array.isArray(base.parameters_schema) ? base.parameters_schema : []
  let toolLabel = base.tool_label
  let resolvedToolName = base.tool_name
  const preferred = activeTool
    ? toolYamlPaths(files).find((path) => {
      const stem = path.replace(/^tools\//, '').replace(/\.ya?ml$/, '')
      if (stem === activeTool)
        return true
      // Allow underscore form to match legacy hyphenated tool filenames.
      return stem.replace(/-/g, '_') === String(activeTool).replace(/-/g, '_')
    })
    : toolYamlPaths(files)[0]

  if (preferred && files[preferred]) {
    try {
      const toolDoc = loadYaml(files[preferred]) || {}
      if (Array.isArray(toolDoc.parameters))
        parametersSchema = toolDoc.parameters
      const identity = toolDoc.identity || {}
      resolvedToolName = identity.name || preferred.replace(/^tools\//, '').replace(/\.ya?ml$/, '')
      const label = identity.label
      if (label && typeof label === 'object')
        toolLabel = label.zh_Hans || label.en_US || toolLabel || resolvedToolName
      else if (label)
        toolLabel = String(label)
    }
    catch {
      // keep existing preview fields
    }
  }

  const providerName = providerIdentityName || base.provider_name || ''
  const providerId = normalizePluginProviderId(base.provider_id, { providerName })

  const toolNameOut = sanitizeToolIdentityName(resolvedToolName || base.tool_name || '')
    || resolvedToolName
    || base.tool_name

  return {
    ...base,
    provider_id: providerId || base.provider_id,
    provider_name: providerName || base.provider_name,
    tool_name: toolNameOut,
    tool_label: toolLabel || base.tool_label || toolNameOut,
    parameters_schema: parametersSchema,
    credentials_schema: credentialsSchema,
  }
}
