/**
 * Chatflow draft features helpers.
 * Contrasts Dify features.tsx / OpeningStatement + suggested_questions_after_answer.
 */

/** Contrasts Dify CUSTOM_FOLLOW_UP_PROMPT_MAX_LENGTH */
export const CUSTOM_FOLLOW_UP_PROMPT_MAX_LENGTH = 1000

/** Contrasts Dify follow-up DEFAULT_COMPLETION_PARAMS (MVP subset). */
export const DEFAULT_FOLLOW_UP_COMPLETION_PARAMS = {
  temperature: 0.7,
  top_p: 1,
  max_tokens: 512,
}

/**
 * Contrasts api DEFAULT_SUGGESTED_QUESTIONS_AFTER_ANSWER_INSTRUCTION_PROMPT
 * (shown read-only when prompt mode = default).
 */
export const DEFAULT_FOLLOW_UP_PROMPT = (
  'Please help me predict the three most likely questions that human would ask, '
  + 'and keep each question under 20 characters.\n'
  + "MAKE SURE your output is the SAME language as the Assistant's latest response. "
  + 'The output must be an array in JSON format following the specified schema:\n'
  + '["question1","question2","question3"]\n'
)

/**
 * @typedef {{
 *   provider: string,
 *   name: string,
 *   mode?: string,
 *   completion_params?: Record<string, unknown>,
 * }} FollowUpModel
 */

/**
 * @typedef {{
 *   enabled: boolean,
 *   model?: FollowUpModel,
 *   prompt?: string,
 * }} SuggestedAfterAnswer
 */

/**
 * @typedef {{
 *   enabled: boolean,
 *   number_limits: number,
 *   transfer_methods: string[],
 * }} FileUploadImage
 */

/**
 * @typedef {{
 *   enabled: boolean,
 *   image: FileUploadImage,
 *   allowed_file_types: string[],
 *   allowed_file_extensions: string[],
 *   allowed_file_upload_methods: string[],
 *   number_limits: number,
 * }} FileUploadFeature
 */

/**
 * @typedef {{
 *   opening_statement?: string,
 *   suggested_questions?: string[],
 *   suggested_questions_after_answer?: SuggestedAfterAnswer,
 *   retriever_resource?: { enabled?: boolean },
 *   file_upload?: FileUploadFeature,
 *   text_to_speech?: TextToSpeechFeature,
 *   speech_to_text?: { enabled?: boolean },
 *   [key: string]: unknown,
 * }} WorkflowFeatures
 */

/**
 * @typedef {{
 *   enabled: boolean,
 *   language: string,
 *   voice: string,
 *   autoPlay: 'enabled' | 'disabled',
 * }} TextToSpeechFeature
 */

/** Contrasts Dify DEFAULT_FILE_NUMBER_LIMITS / buildInitialFeatures */
export const DEFAULT_FILE_UPLOAD_NUMBER_LIMITS = 3

/** Contrasts Dify MAX_FILE_UPLOAD_LIMIT */
export const MAX_FILE_UPLOAD_LIMIT = 10

export const FILE_UPLOAD_TYPE_OPTIONS = [
  { value: 'image', label: '图片' },
  { value: 'document', label: '文档' },
  { value: 'audio', label: '音频' },
  { value: 'video', label: '视频' },
]

export const FILE_UPLOAD_METHOD_OPTIONS = [
  { value: 'local_file', label: '本地上传' },
  { value: 'remote_url', label: '粘贴链接' },
]

/**
 * @returns {FileUploadFeature}
 */
export function createDefaultFileUpload(enabled = false) {
  return {
    enabled: Boolean(enabled),
    image: {
      enabled: Boolean(enabled),
      number_limits: DEFAULT_FILE_UPLOAD_NUMBER_LIMITS,
      transfer_methods: ['local_file', 'remote_url'],
    },
    allowed_file_types: ['image'],
    allowed_file_extensions: [],
    allowed_file_upload_methods: ['local_file', 'remote_url'],
    number_limits: DEFAULT_FILE_UPLOAD_NUMBER_LIMITS,
  }
}

/**
 * @param {unknown} value
 * @returns {number}
 */
export function clampFileUploadNumberLimits(value) {
  const n = Number(value)
  if (!Number.isFinite(n))
    return DEFAULT_FILE_UPLOAD_NUMBER_LIMITS
  return Math.min(MAX_FILE_UPLOAD_LIMIT, Math.max(1, Math.round(n)))
}

/**
 * @param {unknown} types
 * @returns {string[]}
 */
export function normalizeFileUploadTypes(types) {
  const allowed = new Set(FILE_UPLOAD_TYPE_OPTIONS.map(o => o.value))
  const list = (Array.isArray(types) ? types : [])
    .map(t => String(t || '').trim())
    .filter(t => allowed.has(t))
  return [...new Set(list)]
}

/**
 * @param {unknown} methods
 * @returns {string[]}
 */
export function normalizeFileUploadMethods(methods) {
  const allowed = new Set(FILE_UPLOAD_METHOD_OPTIONS.map(o => o.value))
  const list = (Array.isArray(methods) ? methods : [])
    .map(m => String(m || '').trim())
    .filter(m => allowed.has(m))
  const unique = [...new Set(list)]
  return unique.length ? unique : ['local_file', 'remote_url']
}

/**
 * @param {unknown} model
 * @returns {FollowUpModel | undefined}
 */
export function normalizeFollowUpModel(model) {
  if (!model || typeof model !== 'object' || Array.isArray(model))
    return undefined
  const provider = String(model.provider || '').trim()
  const name = String(model.name || '').trim()
  if (!provider || !name)
    return undefined
  return {
    provider,
    name,
    mode: model.mode || 'chat',
    completion_params: model.completion_params && typeof model.completion_params === 'object'
      ? {
          ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS,
          ...model.completion_params,
        }
      : { ...DEFAULT_FOLLOW_UP_COMPLETION_PARAMS },
  }
}

/**
 * @param {unknown} value
 * @returns {SuggestedAfterAnswer}
 */
export function normalizeSuggestedAfterAnswer(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return { enabled: false }
  /** @type {SuggestedAfterAnswer} */
  const result = { enabled: Boolean(value.enabled) }
  const model = normalizeFollowUpModel(value.model)
  if (model)
    result.model = model
  if (typeof value.prompt === 'string') {
    const prompt = value.prompt.trim().slice(0, CUSTOM_FOLLOW_UP_PROMPT_MAX_LENGTH)
    if (prompt)
      result.prompt = prompt
  }
  return result
}

/**
 * @param {SuggestedAfterAnswer | null | undefined} followUp
 * @returns {string}
 */
export function getFollowUpModelSummary(followUp) {
  const model = normalizeFollowUpModel(followUp?.model)
  return model?.name || '系统默认模型'
}

/**
 * @param {unknown} features
 * @returns {WorkflowFeatures}
 */
export function normalizeWorkflowFeatures(features) {
  let value = features
  if (typeof value === 'string') {
    try {
      value = JSON.parse(value)
    }
    catch {
      value = null
    }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {
      opening_statement: '',
      suggested_questions: [],
      suggested_questions_after_answer: { enabled: false },
      retriever_resource: { enabled: true },
      file_upload: createDefaultFileUpload(false),
      text_to_speech: createDefaultTextToSpeech(false),
      speech_to_text: { enabled: false },
    }
  }

  const opening = typeof value.opening_statement === 'string'
    ? value.opening_statement
    : ''
  const suggested = Array.isArray(value.suggested_questions)
    ? value.suggested_questions.map(q => String(q ?? '').trim()).filter(Boolean)
    : []

  const retriever = normalizeRetrieverResource(value.retriever_resource)
  const fileUpload = normalizeFileUpload(value.file_upload)
  const textToSpeech = normalizeTextToSpeech(value.text_to_speech)
  const speechToText = normalizeSpeechToText(value.speech_to_text)

  return {
    ...value,
    opening_statement: opening,
    suggested_questions: suggested,
    suggested_questions_after_answer: normalizeSuggestedAfterAnswer(value.suggested_questions_after_answer),
    retriever_resource: retriever,
    file_upload: fileUpload,
    text_to_speech: textToSpeech,
    speech_to_text: speechToText,
  }
}

/**
 * @param {unknown} value
 * @returns {{ enabled: boolean }}
 */
export function normalizeRetrieverResource(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return { enabled: true }
  return { enabled: Boolean(value.enabled) }
}

/**
 * Contrasts Dify buildInitialFeatures file / file_upload.
 * @param {unknown} value
 * @returns {FileUploadFeature}
 */
export function normalizeFileUpload(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return createDefaultFileUpload(false)

  const numberLimits = clampFileUploadNumberLimits(
    value.number_limits ?? value.image?.number_limits,
  )
  const methods = normalizeFileUploadMethods(
    Array.isArray(value.allowed_file_upload_methods) && value.allowed_file_upload_methods.length
      ? value.allowed_file_upload_methods
      : value.image?.transfer_methods,
  )
  const types = normalizeFileUploadTypes(value.allowed_file_types)
  const imageSrc = value.image && typeof value.image === 'object' && !Array.isArray(value.image)
    ? value.image
    : null
  const enabled = Boolean(value.enabled || imageSrc?.enabled)

  return {
    enabled,
    image: {
      enabled: Boolean(imageSrc?.enabled ?? enabled),
      number_limits: clampFileUploadNumberLimits(imageSrc?.number_limits ?? numberLimits),
      transfer_methods: Array.isArray(imageSrc?.transfer_methods) && imageSrc.transfer_methods.length
        ? normalizeFileUploadMethods(imageSrc.transfer_methods)
        : [...methods],
    },
    allowed_file_types: types.length ? types : ['image'],
    allowed_file_extensions: Array.isArray(value.allowed_file_extensions)
      ? value.allowed_file_extensions.map(String)
      : [],
    allowed_file_upload_methods: methods,
    number_limits: numberLimits,
  }
}

/**
 * @param {WorkflowFeatures} features
 * @returns {boolean}
 */
export function isCitationEnabled(features) {
  return Boolean(normalizeWorkflowFeatures(features).retriever_resource?.enabled)
}

/**
 * @param {WorkflowFeatures} features
 * @returns {boolean}
 */
export function isFileUploadEnabled(features) {
  return Boolean(normalizeWorkflowFeatures(features).file_upload?.enabled)
}

/**
 * @param {WorkflowFeatures} features
 * @returns {number}
 */
export function getFileUploadNumberLimits(features) {
  const fileUpload = normalizeWorkflowFeatures(features).file_upload
  return Number(fileUpload?.number_limits)
    || Number(fileUpload?.image?.number_limits)
    || DEFAULT_FILE_UPLOAD_NUMBER_LIMITS
}

/**
 * HTML accept for chat composer (MVP: image-only defaults).
 * @param {WorkflowFeatures} features
 * @returns {string}
 */
export function getFileUploadAccept(features) {
  const types = normalizeWorkflowFeatures(features).file_upload?.allowed_file_types || []
  if (!types.length || types.every(t => t === 'image'))
    return 'image/*'
  return ''
}

/**
 * @param {WorkflowFeatures} features
 * @returns {string[]}
 */
export function getFileUploadMethods(features) {
  const methods = normalizeWorkflowFeatures(features).file_upload?.allowed_file_upload_methods
  if (Array.isArray(methods) && methods.length)
    return methods.map(String)
  return ['local_file', 'remote_url']
}

/**
 * @param {WorkflowFeatures} features
 * @returns {boolean}
 */
export function allowsFileUploadLocal(features) {
  return isFileUploadEnabled(features) && getFileUploadMethods(features).includes('local_file')
}

/**
 * @param {WorkflowFeatures} features
 * @returns {boolean}
 */
export function allowsFileUploadRemote(features) {
  return isFileUploadEnabled(features) && getFileUploadMethods(features).includes('remote_url')
}

/**
 * @returns {TextToSpeechFeature}
 */
export function createDefaultTextToSpeech(enabled = false) {
  return {
    enabled: Boolean(enabled),
    language: '',
    voice: '',
    autoPlay: 'disabled',
  }
}

/**
 * @param {unknown} value
 * @returns {TextToSpeechFeature}
 */
export function normalizeTextToSpeech(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return createDefaultTextToSpeech(false)
  const autoPlay = value.autoPlay === 'enabled' || value.autoPlay === true
    ? 'enabled'
    : 'disabled'
  return {
    enabled: Boolean(value.enabled),
    language: String(value.language || '').trim(),
    voice: String(value.voice || '').trim(),
    autoPlay,
  }
}

/**
 * @param {unknown} value
 * @returns {{ enabled: boolean }}
 */
export function normalizeSpeechToText(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return { enabled: false }
  return { enabled: Boolean(value.enabled) }
}

/**
 * @param {WorkflowFeatures} features
 * @returns {boolean}
 */
export function isTextToSpeechEnabled(features) {
  return Boolean(normalizeWorkflowFeatures(features).text_to_speech?.enabled)
}

/**
 * @param {WorkflowFeatures} features
 * @returns {boolean}
 */
export function isSpeechToTextEnabled(features) {
  return Boolean(normalizeWorkflowFeatures(features).speech_to_text?.enabled)
}

/**
 * @param {WorkflowFeatures} features
 * @returns {string}
 */
export function getTextToSpeechVoice(features) {
  return String(normalizeWorkflowFeatures(features).text_to_speech?.voice || '').trim()
}

/**
 * Summary line for FeaturesPanel (types · methods · limit).
 * @param {FileUploadFeature | WorkflowFeatures | null | undefined} value
 * @returns {string}
 */
export function getFileUploadSummary(value) {
  const fileUpload = value && typeof value === 'object' && value.file_upload
    ? normalizeFileUpload(value.file_upload)
    : normalizeFileUpload(value)
  const labelMap = Object.fromEntries(FILE_UPLOAD_TYPE_OPTIONS.map(o => [o.value, o.label]))
  const types = (fileUpload.allowed_file_types || [])
    .map(t => labelMap[t] || t)
    .join('、') || '无'
  const methods = fileUpload.allowed_file_upload_methods || []
  const hasLocal = methods.includes('local_file')
  const hasRemote = methods.includes('remote_url')
  const methodText = hasLocal && hasRemote
    ? '本地+链接'
    : (hasRemote ? '链接' : '本地')
  return `类型：${types} · 方式：${methodText} · 上限：${fileUpload.number_limits}`
}

/**
 * @param {WorkflowFeatures} features
 * @returns {boolean}
 */
export function isOpeningEnabled(features) {
  const normalized = normalizeWorkflowFeatures(features)
  return Boolean(
    String(normalized.opening_statement || '').trim()
    || (normalized.suggested_questions || []).length,
  )
}

/**
 * @param {WorkflowFeatures} features
 * @returns {boolean}
 */
export function isSuggestedAfterAnswerEnabled(features) {
  return Boolean(normalizeWorkflowFeatures(features).suggested_questions_after_answer?.enabled)
}

/**
 * Build API/draft payload for conversation opener + follow-up.
 * @param {{
 *   enabled: boolean,
 *   openingStatement: string,
 *   suggestedQuestions: string[],
 *   followUpEnabled?: boolean,
 *   followUpModel?: FollowUpModel | null,
 *   followUpPrompt?: string | null,
 *   citationEnabled?: boolean,
 *   fileUploadEnabled?: boolean,
 *   fileUploadTypes?: string[],
 *   fileUploadMethods?: string[],
 *   fileUploadNumberLimits?: number,
 *   textToSpeechEnabled?: boolean,
 *   speechToTextEnabled?: boolean,
 * }} form
 * @param {WorkflowFeatures} [base]
 * @returns {WorkflowFeatures}
 */
export function buildOpeningFeaturesPayload(form, base = {}) {
  const normalized = normalizeWorkflowFeatures(base)
  const enabled = Boolean(form?.enabled)
  const opening = enabled ? String(form?.openingStatement || '').trim() : ''
  const questions = enabled
    ? (Array.isArray(form?.suggestedQuestions) ? form.suggestedQuestions : [])
      .map(q => String(q ?? '').trim())
      .filter(Boolean)
    : []

  const prevFollowUp = normalized.suggested_questions_after_answer || { enabled: false }
  /** @type {SuggestedAfterAnswer} */
  const followUpDraft = {
    enabled: Boolean(form?.followUpEnabled),
    model: prevFollowUp.model,
    prompt: prevFollowUp.prompt,
  }
  if (form && Object.prototype.hasOwnProperty.call(form, 'followUpModel')) {
    const model = normalizeFollowUpModel(form.followUpModel)
    if (model)
      followUpDraft.model = model
    else
      delete followUpDraft.model
  }
  if (form && Object.prototype.hasOwnProperty.call(form, 'followUpPrompt')) {
    const prompt = typeof form.followUpPrompt === 'string' ? form.followUpPrompt.trim() : ''
    if (prompt)
      followUpDraft.prompt = prompt.slice(0, CUSTOM_FOLLOW_UP_PROMPT_MAX_LENGTH)
    else
      delete followUpDraft.prompt
  }

  const citationEnabled = form && Object.prototype.hasOwnProperty.call(form, 'citationEnabled')
    ? Boolean(form.citationEnabled)
    : Boolean(normalized.retriever_resource?.enabled)

  const prevFileUpload = normalizeFileUpload(normalized.file_upload)
  /** @type {FileUploadFeature} */
  let fileUpload = prevFileUpload
  if (form && Object.prototype.hasOwnProperty.call(form, 'fileUploadEnabled')) {
    const on = Boolean(form.fileUploadEnabled)
    let types = prevFileUpload.allowed_file_types
    let methods = prevFileUpload.allowed_file_upload_methods
    let limits = prevFileUpload.number_limits
    if (Object.prototype.hasOwnProperty.call(form, 'fileUploadTypes')) {
      const nextTypes = normalizeFileUploadTypes(form.fileUploadTypes)
      if (nextTypes.length)
        types = nextTypes
    }
    if (Object.prototype.hasOwnProperty.call(form, 'fileUploadMethods'))
      methods = normalizeFileUploadMethods(form.fileUploadMethods)
    if (Object.prototype.hasOwnProperty.call(form, 'fileUploadNumberLimits'))
      limits = clampFileUploadNumberLimits(form.fileUploadNumberLimits)
    fileUpload = normalizeFileUpload({
      ...prevFileUpload,
      enabled: on,
      allowed_file_types: types,
      allowed_file_upload_methods: methods,
      number_limits: limits,
      image: {
        enabled: on,
        number_limits: limits,
        transfer_methods: [...methods],
      },
    })
  }

  const prevTts = normalizeTextToSpeech(normalized.text_to_speech)
  let textToSpeech = prevTts
  if (form && Object.prototype.hasOwnProperty.call(form, 'textToSpeechEnabled')) {
    textToSpeech = normalizeTextToSpeech({
      ...prevTts,
      enabled: Boolean(form.textToSpeechEnabled),
      language: Object.prototype.hasOwnProperty.call(form, 'textToSpeechLanguage')
        ? form.textToSpeechLanguage
        : prevTts.language,
      voice: Object.prototype.hasOwnProperty.call(form, 'textToSpeechVoice')
        ? form.textToSpeechVoice
        : prevTts.voice,
      autoPlay: Object.prototype.hasOwnProperty.call(form, 'textToSpeechAutoPlay')
        ? (form.textToSpeechAutoPlay ? 'enabled' : 'disabled')
        : prevTts.autoPlay,
    })
  }

  const prevStt = normalizeSpeechToText(normalized.speech_to_text)
  let speechToText = prevStt
  if (form && Object.prototype.hasOwnProperty.call(form, 'speechToTextEnabled')) {
    speechToText = normalizeSpeechToText({
      enabled: Boolean(form.speechToTextEnabled),
    })
  }

  return {
    ...normalized,
    opening_statement: opening,
    suggested_questions: questions,
    suggested_questions_after_answer: normalizeSuggestedAfterAnswer(followUpDraft),
    retriever_resource: normalizeRetrieverResource({ enabled: citationEnabled }),
    file_upload: fileUpload,
    text_to_speech: textToSpeech,
    speech_to_text: speechToText,
  }
}

/**
 * @param {WorkflowFeatures} features
 * @returns {{
 *   enabled: boolean,
 *   openingStatement: string,
 *   suggestedQuestions: string[],
 *   followUpEnabled: boolean,
 *   followUpModel: FollowUpModel | null,
 *   followUpPrompt: string,
 *   citationEnabled: boolean,
 *   fileUploadEnabled: boolean,
 *   fileUploadTypes: string[],
 *   fileUploadMethods: string[],
 *   fileUploadNumberLimits: number,
 *   textToSpeechEnabled: boolean,
 *   speechToTextEnabled: boolean,
 * }}
 */
export function featuresToOpeningForm(features) {
  const normalized = normalizeWorkflowFeatures(features)
  const followUp = normalized.suggested_questions_after_answer || { enabled: false }
  const fileUpload = normalized.file_upload || createDefaultFileUpload(false)
  const tts = normalized.text_to_speech || createDefaultTextToSpeech(false)
  const stt = normalized.speech_to_text || { enabled: false }
  return {
    enabled: isOpeningEnabled(normalized),
    openingStatement: normalized.opening_statement || '',
    suggestedQuestions: [...(normalized.suggested_questions || [])],
    followUpEnabled: Boolean(followUp.enabled),
    followUpModel: followUp.model || null,
    followUpPrompt: followUp.prompt || '',
    citationEnabled: Boolean(normalized.retriever_resource?.enabled),
    fileUploadEnabled: Boolean(fileUpload.enabled),
    fileUploadTypes: [...(fileUpload.allowed_file_types || ['image'])],
    fileUploadMethods: [...(fileUpload.allowed_file_upload_methods || ['local_file', 'remote_url'])],
    fileUploadNumberLimits: clampFileUploadNumberLimits(fileUpload.number_limits),
    textToSpeechEnabled: Boolean(tts.enabled),
    textToSpeechLanguage: tts.language || '',
    textToSpeechVoice: tts.voice || '',
    textToSpeechAutoPlay: tts.autoPlay === 'enabled',
    speechToTextEnabled: Boolean(stt.enabled),
  }
}

/**
 * @param {WorkflowFeatures} features
 * @returns {string}
 */
export function getOpeningStatementText(features) {
  return String(normalizeWorkflowFeatures(features).opening_statement || '').trim()
}

/**
 * @param {WorkflowFeatures} features
 * @returns {string[]}
 */
export function getSuggestedQuestions(features) {
  return [...(normalizeWorkflowFeatures(features).suggested_questions || [])]
}

/**
 * Normalize Console suggested-questions response.
 * @param {unknown} payload
 * @returns {string[]}
 */
export function normalizeSuggestedQuestionsResponse(payload) {
  const list = Array.isArray(payload?.data)
    ? payload.data
    : (Array.isArray(payload) ? payload : [])
  return list.map(q => String(q ?? '').trim()).filter(Boolean)
}

/**
 * @param {{ mode?: string, runStatus?: string, features?: WorkflowFeatures, messageId?: string | null }} args
 * @returns {boolean}
 */
export function shouldFetchSuggestedAfterAnswer({
  mode,
  runStatus,
  features,
  messageId,
} = {}) {
  return mode === 'advanced-chat'
    && runStatus === 'succeeded'
    && isSuggestedAfterAnswerEnabled(features)
    && Boolean(messageId)
}
