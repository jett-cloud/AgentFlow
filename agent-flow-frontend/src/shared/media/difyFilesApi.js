import difyClient from '../http/difyClient.js'

/**
 * Console file upload. Contrasts Dify web/service/base.ts `upload` → POST /files/upload.
 * @param {File|Blob} file
 * @param {{ source?: string }} [options]
 * @returns {Promise<object>} FileResponse (expects `id`)
 */
export function uploadConsoleFile(file, { source } = {}) {
  const formData = new FormData()
  formData.append('file', file)
  if (source)
    formData.append('source', source)

  return difyClient.post('/files/upload', formData, {
    // Drop default JSON Content-Type so axios sets multipart boundary for FormData.
    transformRequest: [(data, headers) => {
      if (headers && typeof headers.delete === 'function')
        headers.delete('Content-Type')
      else if (headers)
        delete headers['Content-Type']
      return data
    }],
  })
}

/**
 * Remote URL ingest. Contrasts Dify uploadRemoteFileInfo → POST /remote-files/upload.
 * @param {string} url
 * @returns {Promise<{ id: string, name?: string, size?: number, mime_type?: string, url?: string }>}
 */
export function uploadRemoteFileInfo(url) {
  return difyClient.post('/remote-files/upload', { url })
}
