/**
 * Chat bubble message_files helpers.
 * Contrasts Dify chat question/answer FileList + message_file / message_end.files.
 */

import { normalizeResultFile, normalizeResultFileList } from './resultFiles.js'

/**
 * Build display files from composer pending entities (before send clear).
 * @param {object[]} pending
 * @returns {object[]}
 */
export function normalizeChatMessageFilesFromPending(pending) {
  return (Array.isArray(pending) ? pending : [])
    .filter(file => file && file.progress !== -1)
    .map(file => normalizeResultFile({
      id: file.uploadedId || file.id,
      name: file.name,
      size: file.size,
      mime_type: file.type,
      type: file.supportFileType || file.type,
      url: file.url,
      transfer_method: file.transferMethod,
      upload_file_id: file.uploadedId,
    }))
    .filter(Boolean)
}

/**
 * Merge file lists, prefer later fields for same id.
 * @param {object[]} existing
 * @param {object[]} incoming
 * @returns {object[]}
 */
export function mergeChatMessageFiles(existing, incoming) {
  const list = (Array.isArray(existing) ? existing : []).map(f => ({ ...f }))
  const indexById = new Map()
  list.forEach((file, index) => {
    if (file?.id)
      indexById.set(file.id, index)
  })

  for (const raw of (Array.isArray(incoming) ? incoming : [])) {
    const file = normalizeResultFile(raw)
    if (!file)
      continue
    if (file.id && indexById.has(file.id)) {
      const idx = indexById.get(file.id)
      list[idx] = { ...list[idx], ...file }
      continue
    }
    if (file.id)
      indexById.set(file.id, list.length)
    list.push(file)
  }
  return list
}

/**
 * Normalize a single SSE message_file event payload.
 * @param {object} event
 * @returns {object | null}
 */
export function normalizeMessageFileEvent(event) {
  if (!event || typeof event !== 'object')
    return null
  const data = event.data && typeof event.data === 'object' ? event.data : {}
  return normalizeResultFile({
    id: event.id || data.id || data.related_id,
    type: event.type || data.type,
    mime_type: event.mime_type || data.mime_type,
    filename: event.filename || data.filename || event.name || data.name,
    name: event.name || data.name,
    url: event.url || data.url || event.remote_url || data.remote_url,
    remote_url: event.remote_url || data.remote_url,
    transfer_method: event.transfer_method || data.transfer_method,
    upload_file_id: event.upload_file_id || data.upload_file_id || event.related_id || data.related_id,
    size: event.size || data.size,
  })
}

/**
 * Files array on message_end-like payloads.
 * @param {object} event
 * @returns {object[]}
 */
export function extractMessageEndFiles(event) {
  if (!event || typeof event !== 'object')
    return []
  const data = event.data && typeof event.data === 'object' ? event.data : {}
  const files = Array.isArray(event.files)
    ? event.files
    : (Array.isArray(data.files) ? data.files : [])
  return normalizeResultFileList(files)
}
