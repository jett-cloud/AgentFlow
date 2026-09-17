/**
 * Build CreateDocumentReq matching Dify web models/datasets.ts + use-document-creation.ts
 */

export const DataSourceType = {
  FILE: 'upload_file',
  NOTION: 'notion_import',
  WEB: 'website_crawl',
}

export const ChunkingMode = {
  text: 'text_model',
  qa: 'qa_model',
  parentChild: 'hierarchical_model',
}

export const IndexingType = {
  QUALIFIED: 'high_quality',
  ECONOMICAL: 'economy',
}

export const DEFAULT_RETRIEVAL_MODEL = {
  search_method: 'semantic_search',
  reranking_enable: false,
  reranking_model: {
    reranking_provider_name: '',
    reranking_model_name: '',
  },
  top_k: 4,
  score_threshold_enabled: false,
  score_threshold: 0.5,
}

export const FALLBACK_PROCESS_RULE = {
  mode: 'custom',
  rules: {
    pre_processing_rules: [
      { id: 'remove_extra_spaces', enabled: true },
      { id: 'remove_urls_emails', enabled: false },
    ],
    segmentation: {
      separator: '\n\n',
      max_tokens: 1024,
      chunk_overlap: 50,
    },
  },
}

/** Normalize GET /datasets/process-rule → ProcessRule used by create APIs */
export function normalizeProcessRule(raw) {
  if (!raw || typeof raw !== 'object')
    return structuredClone(FALLBACK_PROCESS_RULE)

  const rules = raw.rules || FALLBACK_PROCESS_RULE.rules
  const segmentation = rules.segmentation || {}
  return {
    mode: raw.mode || 'custom',
    rules: {
      pre_processing_rules: rules.pre_processing_rules || FALLBACK_PROCESS_RULE.rules.pre_processing_rules,
      segmentation: {
        separator: segmentation.separator ?? segmentation.delimiter ?? '\n\n',
        max_tokens: segmentation.max_tokens ?? 1024,
        chunk_overlap: segmentation.chunk_overlap ?? 50,
      },
      ...(rules.parent_mode ? { parent_mode: rules.parent_mode } : {}),
      ...(rules.subchunk_segmentation
        ? { subchunk_segmentation: rules.subchunk_segmentation }
        : {}),
    },
  }
}

/**
 * @param {{
 *   fileIds: string[],
 *   indexingTechnique?: string,
 *   docForm?: string,
 *   docLanguage?: string,
 *   processRule?: object,
 *   retrievalModel?: object,
 *   embeddingModel?: string,
 *   embeddingModelProvider?: string,
 * }} opts
 */
export function buildFileCreateDocumentPayload({
  fileIds,
  indexingTechnique = IndexingType.QUALIFIED,
  docForm = ChunkingMode.text,
  docLanguage = 'Chinese',
  processRule,
  retrievalModel,
  embeddingModel = '',
  embeddingModelProvider = '',
}) {
  const ids = (fileIds || []).filter(Boolean)
  if (!ids.length)
    throw new Error('至少需要一个已上传文件')

  return {
    data_source: {
      type: DataSourceType.FILE,
      info_list: {
        data_source_type: DataSourceType.FILE,
        file_info_list: { file_ids: ids },
      },
    },
    indexing_technique: indexingTechnique,
    process_rule: processRule || structuredClone(FALLBACK_PROCESS_RULE),
    doc_form: docForm,
    doc_language: docLanguage,
    retrieval_model: retrievalModel || structuredClone(DEFAULT_RETRIEVAL_MODEL),
    embedding_model: embeddingModel,
    embedding_model_provider: embeddingModelProvider,
  }
}

/**
 * Group selected Notion pages by workspace → notion_info_list (Dify getNotionInfo).
 * @param {Array<{ page_id: string, page_name?: string, page_icon?: any, type?: string, workspace_id: string }>} pages
 * @param {string} credentialId
 */
export function buildNotionInfoList(pages, credentialId) {
  if (!credentialId)
    throw new Error('请选择 Notion 凭证')
  const list = Array.isArray(pages) ? pages : []
  if (!list.length)
    throw new Error('请至少选择一个 Notion 页面')

  const byWorkspace = new Map()
  for (const page of list) {
    const workspaceId = page.workspace_id || page.workspaceId || ''
    if (!workspaceId)
      throw new Error(`页面 ${page.page_name || page.page_id} 缺少 workspace_id`)
    if (!byWorkspace.has(workspaceId))
      byWorkspace.set(workspaceId, [])
    byWorkspace.get(workspaceId).push({
      page_id: page.page_id,
      page_name: page.page_name || '',
      page_icon: page.page_icon || null,
      type: page.type || 'page',
    })
  }

  return [...byWorkspace.entries()].map(([workspace_id, workspacePages]) => ({
    credential_id: credentialId,
    workspace_id,
    pages: workspacePages,
  }))
}

export function buildNotionCreateDocumentPayload({
  pages,
  credentialId,
  indexingTechnique = IndexingType.QUALIFIED,
  docForm = ChunkingMode.text,
  docLanguage = 'Chinese',
  processRule,
  retrievalModel,
  embeddingModel = '',
  embeddingModelProvider = '',
}) {
  return {
    data_source: {
      type: DataSourceType.NOTION,
      info_list: {
        data_source_type: DataSourceType.NOTION,
        notion_info_list: buildNotionInfoList(pages, credentialId),
      },
    },
    indexing_technique: indexingTechnique,
    process_rule: processRule || structuredClone(FALLBACK_PROCESS_RULE),
    doc_form: docForm,
    doc_language: docLanguage,
    retrieval_model: retrievalModel || structuredClone(DEFAULT_RETRIEVAL_MODEL),
    embedding_model: embeddingModel,
    embedding_model_provider: embeddingModelProvider,
  }
}

export function buildWebsiteCreateDocumentPayload({
  provider,
  jobId,
  urls,
  onlyMainContent = true,
  indexingTechnique = IndexingType.QUALIFIED,
  docForm = ChunkingMode.text,
  docLanguage = 'Chinese',
  processRule,
  retrievalModel,
  embeddingModel = '',
  embeddingModelProvider = '',
}) {
  const list = (urls || []).filter(Boolean)
  if (!provider)
    throw new Error('请选择爬取提供商')
  if (!jobId)
    throw new Error('缺少爬取任务 ID')
  if (!list.length)
    throw new Error('请至少选择一个网页')

  return {
    data_source: {
      type: DataSourceType.WEB,
      info_list: {
        data_source_type: DataSourceType.WEB,
        website_info_list: {
          provider,
          job_id: jobId,
          urls: list,
          only_main_content: onlyMainContent,
        },
      },
    },
    indexing_technique: indexingTechnique,
    process_rule: processRule || structuredClone(FALLBACK_PROCESS_RULE),
    doc_form: docForm,
    doc_language: docLanguage,
    retrieval_model: retrievalModel || structuredClone(DEFAULT_RETRIEVAL_MODEL),
    embedding_model: embeddingModel,
    embedding_model_provider: embeddingModelProvider,
  }
}

export const DEFAULT_CRAWL_OPTIONS = {
  crawl_sub_pages: true,
  only_main_content: true,
  includes: '',
  excludes: '',
  limit: 10,
  max_depth: '',
  use_sitemap: true,
}

export function isTerminalIndexingStatus(status) {
  const s = String(status || '').toLowerCase()
  return s === 'completed' || s === 'error' || s === 'paused'
}

function unescapeSeparator(value) {
  return String(value ?? '').replace(/\\n/g, '\n')
}

export function buildWizardProcessRule({
  docForm = ChunkingMode.text,
  separator = '\n\n',
  maxTokens = 1024,
  chunkOverlap = 50,
  removeExtraSpaces = true,
  removeUrlsEmails = false,
  parentMode = 'paragraph',
  childSeparator = '\n',
  childMaxTokens = 512,
} = {}) {
  const pre_processing_rules = [
    { id: 'remove_extra_spaces', enabled: Boolean(removeExtraSpaces) },
    { id: 'remove_urls_emails', enabled: Boolean(removeUrlsEmails) },
  ]
  if (docForm === ChunkingMode.parentChild) {
    return {
      mode: 'hierarchical',
      rules: {
        pre_processing_rules,
        segmentation: {
          separator: unescapeSeparator(separator),
          max_tokens: maxTokens,
        },
        parent_mode: parentMode || 'paragraph',
        subchunk_segmentation: {
          separator: unescapeSeparator(childSeparator),
          max_tokens: childMaxTokens,
        },
      },
    }
  }
  return {
    mode: 'custom',
    rules: {
      pre_processing_rules,
      segmentation: {
        separator: unescapeSeparator(separator),
        max_tokens: maxTokens,
        chunk_overlap: chunkOverlap,
      },
    },
  }
}

export function buildIndexingEstimateBody({
  dataSourceType,
  fileIds,
  notionInfoList,
  websiteInfoList,
  indexingTechnique,
  processRule,
  docForm,
  docLanguage,
  datasetId,
}) {
  let info_list
  if (dataSourceType === DataSourceType.NOTION) {
    info_list = {
      data_source_type: DataSourceType.NOTION,
      notion_info_list: notionInfoList,
    }
  }
  else if (dataSourceType === DataSourceType.WEB) {
    info_list = {
      data_source_type: DataSourceType.WEB,
      website_info_list: websiteInfoList,
    }
  }
  else {
    info_list = {
      data_source_type: DataSourceType.FILE,
      file_info_list: { file_ids: fileIds || [] },
    }
  }
  return {
    info_list,
    process_rule: processRule,
    indexing_technique: indexingTechnique,
    doc_form: docForm,
    doc_language: docLanguage,
    ...(datasetId ? { dataset_id: datasetId } : {}),
  }
}
