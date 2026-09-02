/**
 * RESULT file extraction helpers.
 * Contrasts Dify getFilesInLogs / getProcessedFilesFromResponse.
 */

const DIFY_FILE_IDENTITY = '__dify__file__'

/**
 * @param {object} fileItem
 * @returns {object}
 */
export function normalizeResultFile(fileItem) {
  if (!fileItem || typeof fileItem !== 'object')
    return null
  return {
    id: fileItem.related_id || fileItem.upload_file_id || fileItem.id || '',
    name: fileItem.filename || fileItem.name || 'file',
    size: fileItem.size || 0,
    type: fileItem.mime_type || fileItem.type || '',
    supportFileType: fileItem.type || fileItem.supportFileType || '',
    url: fileItem.url || fileItem.remote_url || '',
    transferMethod: fileItem.transfer_method || fileItem.transferMethod || '',
  }
}

/**
 * @param {unknown[]} files
 * @returns {object[]}
 */
export function normalizeResultFileList(files) {
  return (Array.isArray(files) ? files : [])
    .map(normalizeResultFile)
    .filter(Boolean)
}

/**
 * Extract `{ varName, list }[]` from workflow outputs.
 * @param {Record<string, unknown> | null | undefined} rawData
 * @returns {Array<{ varName: string, list: object[] }>}
 */
export function getFilesInLogs(rawData) {
  if (!rawData || typeof rawData !== 'object' || Array.isArray(rawData))
    return []

  return Object.keys(rawData)
    .map((key) => {
      const value = rawData[key]
      if (value && typeof value === 'object' && !Array.isArray(value)
        && value.dify_model_identity === DIFY_FILE_IDENTITY) {
        return {
          varName: key,
          list: normalizeResultFileList([value]),
        }
      }
      if (Array.isArray(value)
        && value.some(item => item?.dify_model_identity === DIFY_FILE_IDENTITY)) {
        return {
          varName: key,
          list: normalizeResultFileList(
            value.filter(item => item?.dify_model_identity === DIFY_FILE_IDENTITY),
          ),
        }
      }
      return null
    })
    .filter(Boolean)
}

/**
 * @param {Array<{ varName: string, list: object[] }>} groups
 * @returns {number}
 */
export function countResultFiles(groups) {
  return (Array.isArray(groups) ? groups : [])
    .reduce((sum, group) => sum + (Array.isArray(group?.list) ? group.list.length : 0), 0)
}

/**
 * @param {object} file
 * @returns {boolean}
 */
export function isImageResultFile(file) {
  const type = String(file?.type || file?.supportFileType || '').toLowerCase()
  if (type.startsWith('image/') || type === 'image')
    return true
  const name = String(file?.name || '').toLowerCase()
  return /\.(png|jpe?g|gif|webp|bmp|svg)$/.test(name)
}

/**
 * Prefer already-grouped RESULT files; else extract from outputs.
 * @param {object | null | undefined} result
 * @returns {Array<{ varName: string, list: object[] }>}
 */
export function resolveResultFileGroups(result) {
  if (!result || typeof result !== 'object')
    return []
  const files = result.files
  if (Array.isArray(files) && files.length
    && files.every(item => item && typeof item === 'object' && Array.isArray(item.list))) {
    return files.map(group => ({
      varName: group.varName || group.variable || 'files',
      list: normalizeResultFileList(group.list),
    })).filter(group => group.list.length)
  }
  return getFilesInLogs(result.outputs)
}
