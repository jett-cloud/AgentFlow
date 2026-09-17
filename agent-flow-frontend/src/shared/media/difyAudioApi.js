import difyClient from '../http/difyClient.js'

/**
 * Console text-to-speech.
 * Contrasts Dify POST /apps/{id}/text-to-audio
 * @param {string} appId
 * @param {{ text: string, voice?: string, messageId?: string, streaming?: boolean }} payload
 * @returns {Promise<Blob>}
 */
export async function textToAudio(appId, {
  text,
  voice = '',
  messageId = '',
  streaming = false,
} = {}) {
  const body = {
    text: String(text || ''),
    streaming: Boolean(streaming),
  }
  if (voice)
    body.voice = voice
  if (messageId)
    body.message_id = messageId

  // Bypass default interceptor unwrap — need raw blob response.
  const response = await difyClient.post(`/apps/${appId}/text-to-audio`, body, {
    responseType: 'blob',
    transformResponse: [(data) => data],
    silent: true,
  })
  if (response instanceof Blob)
    return response
  return new Blob([response], { type: 'audio/mpeg' })
}

/**
 * List TTS voices for a language.
 * Contrasts Dify GET /apps/{id}/text-to-audio/voices
 * @param {string} appId
 * @param {string} [language]
 * @returns {Promise<Array<{ name: string, value: string }>>}
 */
export async function listTtsVoices(appId, language = 'zh-Hans') {
  const data = await difyClient.get(`/apps/${appId}/text-to-audio/voices`, {
    params: { language },
    silent: true,
  })
  const list = Array.isArray(data) ? data : (Array.isArray(data?.data) ? data.data : [])
  return list.map(item => ({
    name: String(item?.name || item?.value || ''),
    value: String(item?.value || item?.name || ''),
  })).filter(item => item.value)
}

/**
 * Console speech-to-text.
 * Contrasts Dify POST /apps/{id}/audio-to-text (multipart file)
 * @param {string} appId
 * @param {Blob | File} file
 * @returns {Promise<string>}
 */
export async function audioToText(appId, file) {
  const formData = new FormData()
  const upload = file instanceof File
    ? file
    : new File([file], 'recording.webm', { type: file?.type || 'audio/webm' })
  formData.append('file', upload)
  const data = await difyClient.post(`/apps/${appId}/audio-to-text`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    silent: true,
  })
  return String(data?.text || data?.data?.text || '')
}
