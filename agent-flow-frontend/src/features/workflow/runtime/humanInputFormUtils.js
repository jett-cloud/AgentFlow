/**
 * Human-input form helpers for debug pause/resume.
 * Contrasts Dify human-input-content utils (display filter + paragraph/select/file).
 */

export const HUMAN_INPUT_TRANSFER_LOCAL = 'local_file'
export const HUMAN_INPUT_TRANSFER_REMOTE = 'remote_url'

const DEFAULT_UPLOAD_METHODS = [HUMAN_INPUT_TRANSFER_LOCAL, HUMAN_INPUT_TRANSFER_REMOTE]

/**
 * @param {unknown[]} list
 * @returns {object[]}
 */
export function getVisibleHumanInputForms(list) {
  return (Array.isArray(list) ? list : []).filter(form => (
    form
    && form.form_token
    && form.display_in_ui !== false
  ))
}

/**
 * @param {object} field
 * @returns {boolean}
 */
export function isTextLikeHumanInputField(field) {
  const type = field?.type
  return type === 'paragraph' || type === 'text' || type === 'select'
}

/**
 * @param {object} field
 * @returns {boolean}
 */
export function isFileHumanInputField(field) {
  return field?.type === 'file'
}

/**
 * @param {object} field
 * @returns {boolean}
 */
export function isFileListHumanInputField(field) {
  return field?.type === 'file-list'
}

/**
 * @param {object} field
 * @returns {boolean}
 */
export function isRenderableHumanInputField(field) {
  return isTextLikeHumanInputField(field)
    || isFileHumanInputField(field)
    || isFileListHumanInputField(field)
}

/**
 * @param {object} formData
 * @returns {object[]}
 */
export function getRenderableHumanInputFields(formData) {
  return (Array.isArray(formData?.inputs) ? formData.inputs : [])
    .filter(isRenderableHumanInputField)
}

/**
 * @param {object} field
 * @returns {string[]}
 */
export function getHumanInputSelectOptions(field) {
  const fromSource = field?.option_source?.value
  if (Array.isArray(fromSource))
    return fromSource.map(v => String(v ?? '')).filter(Boolean)
  if (Array.isArray(field?.options))
    return field.options.map(v => String(v ?? '')).filter(Boolean)
  return []
}

/**
 * Contrasts Dify file-list `number_limits || 5`.
 * @param {object} field
 * @returns {number}
 */
export function getHumanInputFileNumberLimit(field) {
  if (isFileHumanInputField(field))
    return 1
  const limit = Number(field?.number_limits)
  if (Number.isFinite(limit) && limit > 0)
    return limit
  return 5
}

/**
 * Contrasts Dify allowed_file_upload_methods (default local + remote).
 * @param {object} field
 * @returns {string[]}
 */
export function getHumanInputUploadMethods(field) {
  const methods = field?.allowed_file_upload_methods
  if (Array.isArray(methods) && methods.length)
    return methods.map(m => String(m)).filter(Boolean)
  return [...DEFAULT_UPLOAD_METHODS]
}

/**
 * @param {object} field
 * @returns {boolean}
 */
export function allowsLocalHumanInputUpload(field) {
  return getHumanInputUploadMethods(field).includes(HUMAN_INPUT_TRANSFER_LOCAL)
}

/**
 * @param {object} field
 * @returns {boolean}
 */
export function allowsRemoteHumanInputUpload(field) {
  return getHumanInputUploadMethods(field).includes(HUMAN_INPUT_TRANSFER_REMOTE)
}

/**
 * @param {string} url
 * @returns {boolean}
 */
export function isValidRemoteFileUrl(url) {
  const raw = String(url || '').trim()
  if (!raw)
    return false
  try {
    const parsed = new URL(raw)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  }
  catch {
    return false
  }
}

/**
 * Rough SupportUploadFileTypes guess from mime / name.
 * @param {string} [fileName]
 * @param {string} [mimeType]
 * @returns {string}
 */
export function guessSupportFileType(fileName = '', mimeType = '') {
  const mime = String(mimeType || '').toLowerCase()
  if (mime.startsWith('image/'))
    return 'image'
  if (mime.startsWith('audio/'))
    return 'audio'
  if (mime.startsWith('video/'))
    return 'video'
  const ext = String(fileName || '').split('.').pop()?.toLowerCase() || ''
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].includes(ext))
    return 'image'
  if (['mp3', 'wav', 'm4a', 'ogg', 'flac'].includes(ext))
    return 'audio'
  if (['mp4', 'webm', 'mov', 'avi', 'mkv'].includes(ext))
    return 'video'
  return 'document'
}

/**
 * Local pending entity before / after Console upload.
 * Contrasts Dify FileEntity subset used by getProcessedFiles.
 * @param {File} file
 * @returns {object}
 */
export function createLocalHumanInputFileEntity(file) {
  const id = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  return {
    id,
    name: file?.name || 'file',
    size: file?.size || 0,
    type: file?.type || '',
    supportFileType: guessSupportFileType(file?.name, file?.type),
    transferMethod: HUMAN_INPUT_TRANSFER_LOCAL,
    progress: 0,
    uploadedId: '',
    url: '',
    _file: file,
  }
}

/**
 * Pending remote_url entity before Console remote-files upload.
 * @param {string} url
 * @returns {object}
 */
export function createRemoteHumanInputFileEntity(url) {
  const trimmed = String(url || '').trim()
  const id = `remote-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  return {
    id,
    name: trimmed || 'remote-file',
    size: 0,
    type: '',
    supportFileType: '',
    transferMethod: HUMAN_INPUT_TRANSFER_REMOTE,
    progress: 0,
    uploadedId: '',
    url: trimmed,
  }
}

/**
 * @param {object} entity
 * @param {object} response Upload API payload
 * @returns {object}
 */
export function markHumanInputFileUploaded(entity, response) {
  const uploadedId = response?.id || response?.upload_file_id || ''
  const name = response?.name || entity.name
  const mime = response?.mime_type || entity.type
  return {
    ...entity,
    progress: 100,
    uploadedId,
    name,
    size: response?.size ?? entity.size,
    url: response?.url || entity.url || '',
    type: mime,
    supportFileType: mime || name
      ? guessSupportFileType(name, mime)
      : (entity.supportFileType || 'document'),
  }
}

/**
 * @param {object} file
 * @returns {boolean}
 */
export function isHumanInputFileUploaded(file) {
  return !!(file && typeof file === 'object' && file.uploadedId)
}

/**
 * @param {object} formData
 * @returns {Record<string, unknown>}
 */
export function initializeHumanInputValues(formData) {
  const defaults = formData?.resolved_default_values && typeof formData.resolved_default_values === 'object'
    ? formData.resolved_default_values
    : {}
  /** @type {Record<string, unknown>} */
  const values = {}
  for (const field of getRenderableHumanInputFields(formData)) {
    const name = field.output_variable_name
    if (!name)
      continue
    if (isFileHumanInputField(field)) {
      values[name] = null
      continue
    }
    if (isFileListHumanInputField(field)) {
      values[name] = []
      continue
    }
    const resolved = defaults[name]
    if (typeof resolved === 'string') {
      values[name] = resolved
      continue
    }
    if (field.type === 'select') {
      values[name] = ''
      continue
    }
    if (field.default && typeof field.default === 'object' && typeof field.default.value === 'string')
      values[name] = field.default.value
    else if (typeof field.default_value === 'string')
      values[name] = field.default_value
    else
      values[name] = ''
  }
  return values
}

/**
 * Contrasts Dify getProcessedFiles for submit payload.
 * @param {object[]} files
 * @returns {object[]}
 */
export function getProcessedHumanInputFiles(files) {
  return (Array.isArray(files) ? files : [])
    .filter(file => file && file.progress !== -1 && isHumanInputFileUploaded(file))
    .map(file => ({
      type: file.supportFileType || 'document',
      transfer_method: file.transferMethod || HUMAN_INPUT_TRANSFER_LOCAL,
      url: file.url || '',
      upload_file_id: file.uploadedId || '',
    }))
}

/**
 * Contrasts Dify getProcessedHumanInputFormInputs.
 * @param {object[]} fields
 * @param {Record<string, unknown>} values
 * @returns {Record<string, unknown>}
 */
export function getProcessedHumanInputFormInputs(fields, values) {
  const source = values && typeof values === 'object' ? { ...values } : {}
  for (const field of (Array.isArray(fields) ? fields : [])) {
    const name = field?.output_variable_name
    if (!name)
      continue
    const value = source[name]
    if (isFileListHumanInputField(field)) {
      source[name] = getProcessedHumanInputFiles(Array.isArray(value) ? value : [])
      continue
    }
    if (isFileHumanInputField(field)) {
      if (Array.isArray(value)) {
        source[name] = getProcessedHumanInputFiles(value)[0]
        continue
      }
      source[name] = value && typeof value === 'object'
        ? getProcessedHumanInputFiles([value])[0]
        : undefined
    }
  }
  return source
}

/**
 * Required / incomplete file checks before submit.
 * @param {object[]} fields
 * @param {Record<string, unknown>} values
 * @returns {string} empty if ok
 */
export function validateHumanInputValues(fields, values) {
  for (const field of (Array.isArray(fields) ? fields : [])) {
    const name = field?.output_variable_name
    if (!name)
      continue
    const value = values?.[name]
    const label = field.label || name

    if (isFileHumanInputField(field)) {
      const file = Array.isArray(value) ? value[0] : value
      if (field.required && !isHumanInputFileUploaded(file))
        return `请上传必填文件：${label}`
      if (file && typeof file === 'object' && !isHumanInputFileUploaded(file) && file.progress !== -1)
        return `文件仍在上传：${label}`
      continue
    }

    if (isFileListHumanInputField(field)) {
      const list = Array.isArray(value) ? value : []
      if (field.required && (list.length === 0 || !list.every(isHumanInputFileUploaded)))
        return `请上传必填文件：${label}`
      if (list.some(f => f && !isHumanInputFileUploaded(f) && f.progress !== -1))
        return `文件仍在上传：${label}`
      continue
    }

    if (!field.required)
      continue
    if (typeof value !== 'string' || !value.trim())
      return `请填写必填项：${label}`
  }
  return ''
}

/**
 * @param {object[]} list
 * @param {string} nodeId
 * @returns {object[]}
 */
export function removeHumanInputFormByNodeId(list, nodeId) {
  return (Array.isArray(list) ? list : []).filter(item => item?.node_id !== nodeId)
}
