import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildFileCreateDocumentPayload,
  buildNotionCreateDocumentPayload,
  buildWebsiteCreateDocumentPayload,
  buildWizardProcessRule,
  buildIndexingEstimateBody,
  normalizeProcessRule,
  isTerminalIndexingStatus,
  DataSourceType,
  IndexingType,
  ChunkingMode,
} from './createDocumentPayload.js'

test('buildFileCreateDocumentPayload mirrors Dify CreateDocumentReq file shape', () => {
  const payload = buildFileCreateDocumentPayload({
    fileIds: ['f1', 'f2'],
    embeddingModel: 'text-embedding-3-small',
    embeddingModelProvider: 'openai',
  })
  assert.equal(payload.data_source.type, DataSourceType.FILE)
  assert.equal(payload.data_source.info_list.data_source_type, DataSourceType.FILE)
  assert.deepEqual(payload.data_source.info_list.file_info_list.file_ids, ['f1', 'f2'])
  assert.equal(payload.indexing_technique, IndexingType.QUALIFIED)
  assert.equal(payload.doc_form, ChunkingMode.text)
  assert.equal(payload.embedding_model, 'text-embedding-3-small')
  assert.equal(payload.embedding_model_provider, 'openai')
  assert.equal(payload.process_rule.mode, 'custom')
  assert.equal(payload.retrieval_model.search_method, 'semantic_search')
})

test('buildFileCreateDocumentPayload rejects empty files', () => {
  assert.throws(() => buildFileCreateDocumentPayload({ fileIds: [] }), /文件/)
})

test('buildNotionCreateDocumentPayload groups pages by workspace', () => {
  const payload = buildNotionCreateDocumentPayload({
    credentialId: 'cred-1',
    pages: [
      { page_id: 'p1', page_name: 'A', workspace_id: 'w1', type: 'page' },
      { page_id: 'p2', page_name: 'B', workspace_id: 'w1', type: 'page' },
      { page_id: 'p3', page_name: 'C', workspace_id: 'w2', type: 'page' },
    ],
  })
  assert.equal(payload.data_source.type, DataSourceType.NOTION)
  assert.equal(payload.data_source.info_list.notion_info_list.length, 2)
  assert.equal(payload.data_source.info_list.notion_info_list[0].credential_id, 'cred-1')
  assert.equal(payload.data_source.info_list.notion_info_list[0].pages.length, 2)
})

test('buildWebsiteCreateDocumentPayload requires provider/job/urls', () => {
  const payload = buildWebsiteCreateDocumentPayload({
    provider: 'jinareader',
    jobId: 'job-1',
    urls: ['https://example.com/a'],
  })
  assert.equal(payload.data_source.type, DataSourceType.WEB)
  assert.deepEqual(payload.data_source.info_list.website_info_list, {
    provider: 'jinareader',
    job_id: 'job-1',
    urls: ['https://example.com/a'],
    only_main_content: true,
  })
  assert.throws(() => buildWebsiteCreateDocumentPayload({ provider: '', jobId: 'j', urls: ['u'] }), /提供商/)
})

test('normalizeProcessRule maps delimiter to separator', () => {
  const rule = normalizeProcessRule({
    mode: 'custom',
    rules: {
      pre_processing_rules: [],
      segmentation: { delimiter: '\n', max_tokens: 500, chunk_overlap: 10 },
    },
  })
  assert.equal(rule.rules.segmentation.separator, '\n')
  assert.equal(rule.rules.segmentation.max_tokens, 500)
})

test('isTerminalIndexingStatus', () => {
  assert.equal(isTerminalIndexingStatus('completed'), true)
  assert.equal(isTerminalIndexingStatus('indexing'), false)
  assert.equal(isTerminalIndexingStatus('error'), true)
})

test('buildWizardProcessRule writes preprocess toggles and language stays caller-owned', () => {
  const rule = buildWizardProcessRule({
    docForm: ChunkingMode.text,
    separator: '\\n\\n',
    maxTokens: 800,
    chunkOverlap: 20,
    removeExtraSpaces: false,
    removeUrlsEmails: true,
  })
  assert.equal(rule.mode, 'custom')
  assert.deepEqual(rule.rules.pre_processing_rules, [
    { id: 'remove_extra_spaces', enabled: false },
    { id: 'remove_urls_emails', enabled: true },
  ])
  assert.equal(rule.rules.segmentation.separator, '\n\n')
  const payload = buildFileCreateDocumentPayload({
    fileIds: ['f1'],
    docLanguage: 'English',
    processRule: rule,
  })
  assert.equal(payload.doc_language, 'English')
})

test('buildWizardProcessRule includes parent-child fields', () => {
  const rule = buildWizardProcessRule({
    docForm: ChunkingMode.parentChild,
    separator: '\\n\\n',
    maxTokens: 1024,
    parentMode: 'full-doc',
    childSeparator: '\\n',
    childMaxTokens: 256,
  })
  assert.equal(rule.mode, 'hierarchical')
  assert.equal(rule.rules.parent_mode, 'full-doc')
  assert.equal(rule.rules.subchunk_segmentation.separator, '\n')
  assert.equal(rule.rules.subchunk_segmentation.max_tokens, 256)
  assert.equal('chunk_overlap' in rule.rules.segmentation, false)
})

test('buildIndexingEstimateBody uses info_list for file and website sources', () => {
  const fileBody = buildIndexingEstimateBody({
    dataSourceType: DataSourceType.FILE,
    fileIds: ['f1'],
    indexingTechnique: IndexingType.QUALIFIED,
    processRule: buildWizardProcessRule(),
    docForm: ChunkingMode.text,
    docLanguage: 'Chinese',
    datasetId: 'ds-1',
  })
  assert.equal(fileBody.info_list.data_source_type, DataSourceType.FILE)
  assert.deepEqual(fileBody.info_list.file_info_list.file_ids, ['f1'])
  assert.equal(fileBody.doc_language, 'Chinese')
  assert.equal(fileBody.dataset_id, 'ds-1')

  const webBody = buildIndexingEstimateBody({
    dataSourceType: DataSourceType.WEB,
    websiteInfoList: {
      provider: 'jinareader',
      job_id: 'job-1',
      urls: ['https://example.com'],
      only_main_content: true,
    },
    indexingTechnique: IndexingType.ECONOMICAL,
    processRule: buildWizardProcessRule(),
    docForm: ChunkingMode.text,
    docLanguage: 'English',
  })
  assert.equal(webBody.info_list.data_source_type, DataSourceType.WEB)
  assert.equal('dataset_id' in webBody, false)
})
