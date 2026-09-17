/**
 * Trigger browser download for a remote/local file URL.
 * Contrasts Dify web/utils/download.ts downloadUrl.
 *
 * @param {{ url: string, fileName?: string }} options
 */
export function downloadUrl({ url, fileName } = {}) {
  if (!url || typeof document === 'undefined')
    return
  const anchor = document.createElement('a')
  anchor.href = url
  if (fileName)
    anchor.download = fileName
  anchor.rel = 'noopener noreferrer'
  anchor.target = '_blank'
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}
