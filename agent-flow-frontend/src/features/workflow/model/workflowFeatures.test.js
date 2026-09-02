import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildOpeningFeaturesPayload,
  featuresToOpeningForm,
  allowsFileUploadLocal,
  allowsFileUploadRemote,
  clampFileUploadNumberLimits,
  getFileUploadAccept,
  getFileUploadMethods,
  getFileUploadNumberLimits,
  getFileUploadSummary,
  getFollowUpModelSummary,
  getOpeningStatementText,
  getSuggestedQuestions,
  isCitationEnabled,
  isFileUploadEnabled,
  isOpeningEnabled,
  isSpeechToTextEnabled,
  isSuggestedAfterAnswerEnabled,
  isTextToSpeechEnabled,
  normalizeFileUpload,
  normalizeFileUploadMethods,
  normalizeFileUploadTypes,
  normalizeSuggestedQuestionsResponse,
  normalizeWorkflowFeatures,
  shouldFetchSuggestedAfterAnswer,
} from './workflowFeatures.js'

test('normalizeWorkflowFeatures defaults opening fields', () => {
  const empty = normalizeWorkflowFeatures(null)
  assert.equal(empty.opening_statement, '')
  assert.deepEqual(empty.suggested_questions, [])
  assert.equal(empty.suggested_questions_after_answer.enabled, false)
  assert.equal(empty.retriever_resource.enabled, true)
  assert.equal(empty.file_upload.enabled, false)
  assert.deepEqual(empty.file_upload.allowed_file_types, ['image'])
  assert.equal(empty.file_upload.number_limits, 3)
})

test('normalizeWorkflowFeatures trims suggested questions', () => {
  const next = normalizeWorkflowFeatures({
    opening_statement: '你好',
    suggested_questions: [' a ', '', 'b'],
    suggested_questions_after_answer: { enabled: true },
    retriever_resource: { enabled: false },
  })
  assert.equal(next.opening_statement, '你好')
  assert.deepEqual(next.suggested_questions, ['a', 'b'])
  assert.equal(next.suggested_questions_after_answer.enabled, true)
  assert.equal(next.retriever_resource.enabled, false)
})

test('buildOpeningFeaturesPayload clears when disabled', () => {
  const next = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: 'hi',
    suggestedQuestions: ['q1'],
    followUpEnabled: true,
  }, { retriever_resource: { enabled: true }, opening_statement: 'old' })
  assert.equal(next.opening_statement, '')
  assert.deepEqual(next.suggested_questions, [])
  assert.equal(next.suggested_questions_after_answer.enabled, true)
  assert.equal(next.retriever_resource.enabled, true)
})

test('buildOpeningFeaturesPayload keeps enabled opener', () => {
  const next = buildOpeningFeaturesPayload({
    enabled: true,
    openingStatement: ' 欢迎 ',
    suggestedQuestions: ['能做什么？', ''],
    followUpEnabled: false,
  })
  assert.equal(next.opening_statement, '欢迎')
  assert.deepEqual(next.suggested_questions, ['能做什么？'])
  assert.equal(next.suggested_questions_after_answer.enabled, false)
})

test('featuresToOpeningForm and getters', () => {
  const form = featuresToOpeningForm({
    opening_statement: 'Hello',
    suggested_questions: ['A'],
    suggested_questions_after_answer: { enabled: true },
  })
  assert.equal(form.enabled, true)
  assert.equal(form.openingStatement, 'Hello')
  assert.deepEqual(form.suggestedQuestions, ['A'])
  assert.equal(form.followUpEnabled, true)
  assert.equal(isOpeningEnabled({ opening_statement: '' }), false)
  assert.equal(getOpeningStatementText({ opening_statement: ' x ' }), 'x')
  assert.deepEqual(getSuggestedQuestions({ suggested_questions: ['1'] }), ['1'])
  assert.equal(isSuggestedAfterAnswerEnabled({ suggested_questions_after_answer: { enabled: true } }), true)
})

test('normalizeSuggestedQuestionsResponse and shouldFetchSuggestedAfterAnswer', () => {
  assert.deepEqual(normalizeSuggestedQuestionsResponse({ data: [' a ', '', 'b'] }), ['a', 'b'])
  assert.deepEqual(normalizeSuggestedQuestionsResponse(['x']), ['x'])
  assert.equal(shouldFetchSuggestedAfterAnswer({
    mode: 'advanced-chat',
    runStatus: 'succeeded',
    features: { suggested_questions_after_answer: { enabled: true } },
    messageId: 'm1',
  }), true)
  assert.equal(shouldFetchSuggestedAfterAnswer({
    mode: 'workflow',
    runStatus: 'succeeded',
    features: { suggested_questions_after_answer: { enabled: true } },
    messageId: 'm1',
  }), false)
  assert.equal(shouldFetchSuggestedAfterAnswer({
    mode: 'advanced-chat',
    runStatus: 'failed',
    features: { suggested_questions_after_answer: { enabled: true } },
    messageId: 'm1',
  }), false)
})

test('normalizeSuggestedAfterAnswer preserves model and prompt', () => {
  const next = normalizeWorkflowFeatures({
    suggested_questions_after_answer: {
      enabled: true,
      model: { provider: 'openai', name: 'gpt-4o', mode: 'chat', completion_params: { temperature: 0.5 } },
      prompt: '  ask three questions  ',
    },
  }).suggested_questions_after_answer
  assert.equal(next.enabled, true)
  assert.equal(next.model.provider, 'openai')
  assert.equal(next.model.name, 'gpt-4o')
  assert.equal(next.model.completion_params.temperature, 0.5)
  assert.equal(next.prompt, 'ask three questions')
  assert.equal(getFollowUpModelSummary(next), 'gpt-4o')
  assert.equal(getFollowUpModelSummary({ enabled: true }), '系统默认模型')
})

test('buildOpeningFeaturesPayload round-trips follow-up model/prompt', () => {
  const base = {
    suggested_questions_after_answer: {
      enabled: true,
      model: { provider: 'openai', name: 'gpt-4o' },
      prompt: 'old',
    },
  }
  const kept = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: true,
  }, base)
  assert.equal(kept.suggested_questions_after_answer.model.name, 'gpt-4o')
  assert.equal(kept.suggested_questions_after_answer.prompt, 'old')

  const updated = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: true,
    followUpModel: { provider: 'anthropic', name: 'claude' },
    followUpPrompt: 'custom prompt',
  }, base)
  assert.equal(updated.suggested_questions_after_answer.model.provider, 'anthropic')
  assert.equal(updated.suggested_questions_after_answer.prompt, 'custom prompt')

  const cleared = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: true,
    followUpModel: null,
    followUpPrompt: '',
  }, base)
  assert.equal(cleared.suggested_questions_after_answer.model, undefined)
  assert.equal(cleared.suggested_questions_after_answer.prompt, undefined)

  const form = featuresToOpeningForm(updated)
  assert.equal(form.followUpModel.name, 'claude')
  assert.equal(form.followUpPrompt, 'custom prompt')
})

test('citation retriever_resource toggles round-trip', () => {
  assert.equal(isCitationEnabled({ retriever_resource: { enabled: true } }), true)
  assert.equal(isCitationEnabled({ retriever_resource: { enabled: false } }), false)
  assert.equal(isCitationEnabled(null), true)

  const off = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: false,
    citationEnabled: false,
  }, { retriever_resource: { enabled: true } })
  assert.equal(off.retriever_resource.enabled, false)
  assert.equal(featuresToOpeningForm(off).citationEnabled, false)

  const on = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: false,
    citationEnabled: true,
  }, off)
  assert.equal(on.retriever_resource.enabled, true)
})

test('file_upload toggles round-trip with defaults', () => {
  assert.equal(isFileUploadEnabled(null), false)
  assert.equal(isFileUploadEnabled({ file_upload: { enabled: true } }), true)
  assert.equal(getFileUploadNumberLimits(null), 3)
  assert.equal(getFileUploadAccept(null), 'image/*')

  const enabled = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: false,
    fileUploadEnabled: true,
  })
  assert.equal(enabled.file_upload.enabled, true)
  assert.equal(enabled.file_upload.image.enabled, true)
  assert.deepEqual(enabled.file_upload.allowed_file_types, ['image'])
  assert.deepEqual(enabled.file_upload.allowed_file_upload_methods, ['local_file', 'remote_url'])
  assert.equal(enabled.file_upload.number_limits, 3)
  assert.equal(featuresToOpeningForm(enabled).fileUploadEnabled, true)

  const disabled = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: false,
    fileUploadEnabled: false,
  }, enabled)
  assert.equal(disabled.file_upload.enabled, false)
  assert.equal(disabled.file_upload.image.enabled, false)
  assert.deepEqual(disabled.file_upload.allowed_file_types, ['image'])
  assert.equal(featuresToOpeningForm(disabled).fileUploadEnabled, false)

  const normalized = normalizeFileUpload({
    enabled: true,
    number_limits: 5,
    allowed_file_types: ['image', 'document'],
  })
  assert.equal(normalized.number_limits, 5)
  assert.equal(getFileUploadAccept({ file_upload: normalized }), '')
})

test('file_upload methods gate local vs remote attach', () => {
  assert.equal(allowsFileUploadLocal(null), false)
  assert.equal(allowsFileUploadRemote(null), false)
  assert.deepEqual(getFileUploadMethods(null), ['local_file', 'remote_url'])

  const both = {
    file_upload: {
      enabled: true,
      allowed_file_upload_methods: ['local_file', 'remote_url'],
    },
  }
  assert.equal(allowsFileUploadLocal(both), true)
  assert.equal(allowsFileUploadRemote(both), true)

  const localOnly = {
    file_upload: {
      enabled: true,
      allowed_file_upload_methods: ['local_file'],
    },
  }
  assert.equal(allowsFileUploadLocal(localOnly), true)
  assert.equal(allowsFileUploadRemote(localOnly), false)

  const remoteOnly = {
    file_upload: {
      enabled: true,
      allowed_file_upload_methods: ['remote_url'],
    },
  }
  assert.equal(allowsFileUploadLocal(remoteOnly), false)
  assert.equal(allowsFileUploadRemote(remoteOnly), true)
})

test('file_upload settings round-trip types methods limits', () => {
  assert.equal(clampFileUploadNumberLimits(0), 1)
  assert.equal(clampFileUploadNumberLimits(99), 10)
  assert.deepEqual(normalizeFileUploadTypes(['image', 'custom', 'document']), ['image', 'document'])
  assert.deepEqual(normalizeFileUploadMethods([]), ['local_file', 'remote_url'])

  const saved = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: false,
    fileUploadEnabled: true,
    fileUploadTypes: ['document', 'image'],
    fileUploadMethods: ['remote_url'],
    fileUploadNumberLimits: 8,
  })
  assert.equal(saved.file_upload.enabled, true)
  assert.deepEqual(saved.file_upload.allowed_file_types, ['document', 'image'])
  assert.deepEqual(saved.file_upload.allowed_file_upload_methods, ['remote_url'])
  assert.equal(saved.file_upload.number_limits, 8)
  assert.equal(saved.file_upload.image.enabled, true)
  assert.equal(saved.file_upload.image.number_limits, 8)
  assert.deepEqual(saved.file_upload.image.transfer_methods, ['remote_url'])

  const form = featuresToOpeningForm(saved)
  assert.equal(form.fileUploadEnabled, true)
  assert.deepEqual(form.fileUploadTypes, ['document', 'image'])
  assert.deepEqual(form.fileUploadMethods, ['remote_url'])
  assert.equal(form.fileUploadNumberLimits, 8)
  assert.match(getFileUploadSummary(saved.file_upload), /文档、图片/)
  assert.match(getFileUploadSummary(saved.file_upload), /链接/)
  assert.match(getFileUploadSummary(saved.file_upload), /上限：8/)

  // Empty types ignored → keep previous types
  const kept = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: false,
    fileUploadEnabled: true,
    fileUploadTypes: [],
    fileUploadMethods: ['local_file'],
    fileUploadNumberLimits: 2,
  }, saved)
  assert.deepEqual(kept.file_upload.allowed_file_types, ['document', 'image'])
  assert.deepEqual(kept.file_upload.allowed_file_upload_methods, ['local_file'])
  assert.equal(kept.file_upload.number_limits, 2)
})

test('text_to_speech and speech_to_text toggles round-trip', () => {
  assert.equal(isTextToSpeechEnabled(null), false)
  assert.equal(isSpeechToTextEnabled(null), false)

  const enabled = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: false,
    textToSpeechEnabled: true,
    textToSpeechLanguage: 'zh-Hans',
    textToSpeechVoice: 'alloy',
    textToSpeechAutoPlay: true,
    speechToTextEnabled: true,
  })
  assert.equal(enabled.text_to_speech.enabled, true)
  assert.equal(enabled.text_to_speech.language, 'zh-Hans')
  assert.equal(enabled.text_to_speech.voice, 'alloy')
  assert.equal(enabled.text_to_speech.autoPlay, 'enabled')
  assert.equal(enabled.speech_to_text.enabled, true)
  assert.equal(featuresToOpeningForm(enabled).textToSpeechEnabled, true)
  assert.equal(featuresToOpeningForm(enabled).textToSpeechVoice, 'alloy')
  assert.equal(featuresToOpeningForm(enabled).textToSpeechAutoPlay, true)
  assert.equal(isTextToSpeechEnabled(enabled), true)

  const off = buildOpeningFeaturesPayload({
    enabled: false,
    openingStatement: '',
    suggestedQuestions: [],
    followUpEnabled: false,
    textToSpeechEnabled: false,
    speechToTextEnabled: false,
  }, enabled)
  assert.equal(off.text_to_speech.enabled, false)
  assert.equal(off.text_to_speech.voice, 'alloy')
  assert.equal(off.speech_to_text.enabled, false)
})
