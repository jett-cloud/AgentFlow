export async function readBlobErrorMessage(blob) {
  if (!(blob instanceof Blob))
    return ''
  const text = (await blob.text()).trim()
  if (!text)
    return ''
  try {
    const payload = JSON.parse(text)
    return String(payload?.message || payload?.error || text).trim()
  }
  catch {
    return text.slice(0, 200)
  }
}
