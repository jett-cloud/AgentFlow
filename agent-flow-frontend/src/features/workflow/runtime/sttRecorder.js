/**
 * Lightweight MediaRecorder helpers for STT (Dify VoiceInput simplified).
 * Browser MediaRecorder → webm/ogg blob → console audio-to-text.
 */

export const STT_MAX_SECONDS = 120

/**
 * Pick a supported mime type for MediaRecorder.
 * @param {typeof MediaRecorder} [Recorder]
 * @returns {string}
 */
export function pickRecorderMimeType(Recorder = globalThis.MediaRecorder) {
  if (!Recorder?.isTypeSupported)
    return ''
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ]
  return candidates.find(type => Recorder.isTypeSupported(type)) || ''
}

/**
 * @param {Blob[]} chunks
 * @param {string} mimeType
 * @returns {Blob | null}
 */
export function buildRecordingBlob(chunks, mimeType = 'audio/webm') {
  if (!Array.isArray(chunks) || !chunks.length)
    return null
  return new Blob(chunks, { type: mimeType || 'audio/webm' })
}

/**
 * Append transcribed text into the composer field.
 * @param {string} current
 * @param {string} transcript
 */
export function mergeTranscriptIntoQuery(current, transcript) {
  const next = String(transcript || '').trim()
  if (!next)
    return String(current || '')
  const prev = String(current || '').trim()
  return prev ? `${prev} ${next}` : next
}
