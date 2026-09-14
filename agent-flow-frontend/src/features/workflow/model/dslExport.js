const IMPORT_EXPORT_DSL_PERMISSION = 'app.acl.import_export_dsl'

export function canExportWorkflowDsl(permissionKeys) {
  return Array.isArray(permissionKeys) && permissionKeys.includes(IMPORT_EXPORT_DSL_PERMISSION)
}

export function hasSecretEnvironmentVariables(draft) {
  const variables = draft?.environmentVariables
    || draft?.environment_variables
    || draft?.workflow?.environment_variables
    || []
  return Array.isArray(variables) && variables.some(variable => (
    variable?.value_type === 'secret' || variable?.valueType === 'secret'
  ))
}

export function resolveDslExportPlan({ hasSecrets, secretChoice }) {
  if (!hasSecrets || secretChoice === false)
    return 'download-safe'
  if (secretChoice === true)
    return 'request-secrets'
  return 'cancel'
}

export function resolveSecretExportChoice(action) {
  if (action === 'safe')
    return false
  if (action === 'include-secrets')
    return true
  return null
}

export function canContinueEditorDslExport({ persistEditorDraft, draftSaved }) {
  return !persistEditorDraft || draftSaved === true
}

export function getWorkflowDslDownloadName({ payloadName, appName }) {
  return payloadName ?? appName
}

export function createSerialSaver(save) {
  let tail = Promise.resolve()
  return (payload) => {
    const next = tail.catch(() => undefined).then(() => save(payload))
    tail = next
    return next
  }
}

export function downloadWorkflowYaml(yaml, appName, {
  documentImpl = document,
  urlImpl = URL,
  BlobImpl = Blob,
} = {}) {
  const blob = new BlobImpl([yaml], { type: 'application/yaml' })
  const objectUrl = urlImpl.createObjectURL(blob)
  let anchor
  try {
    anchor = documentImpl.createElement('a')
    anchor.href = objectUrl
    anchor.download = `${appName || 'workflow'}.yml`
    documentImpl.body.append(anchor)
    anchor.click()
  }
  finally {
    anchor?.remove?.()
    urlImpl.revokeObjectURL(objectUrl)
  }
}
