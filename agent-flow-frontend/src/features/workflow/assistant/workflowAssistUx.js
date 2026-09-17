const COMPLETION_ASSERTION = 'workflow_structure_reaches_terminal'
const SHA256_PATTERN = /^[0-9a-f]{64}$/

function synchronizedHash(result) {
  if (typeof result === 'string')
    return result
  return String(result?.hash || '')
}

export function isPreviewableAssistGraph(graph) {
  return Boolean(graph && Array.isArray(graph.nodes) && graph.nodes.length > 0)
}

export function normalizeConversationTitle(value) {
  return String(value ?? '').trim().slice(0, 255)
}

export function nextConversationIdAfterDelete(conversations, deletedId, currentId) {
  const remaining = (Array.isArray(conversations) ? conversations : [])
    .filter(item => String(item?.id || '') !== String(deletedId || ''))
  if (String(currentId || '') !== String(deletedId || ''))
    return currentId || remaining[0]?.id || null
  return remaining[0]?.id || null
}

export function canApplyWorkflowAssistCandidate(candidate, appMode) {
  const run = candidate?.latest_run
  const evidence = candidate?.completion_evidence
  const usesContract = evidence?.contract_protocol_version != null
  const contractEvidenceIsComplete = !usesContract || Boolean(
    Number(evidence.contract_protocol_version) === 1
    && Number(evidence.contract_revision) > 0
    && SHA256_PATTERN.test(String(evidence.contract_hash || ''))
    && SHA256_PATTERN.test(String(evidence.graph_hash || ''))
    && Number(evidence.validation_version) > 0
    && candidate?.contract_report?.passed === true,
  )
  return Boolean(
    candidate?.graph
    && !candidate?.active_run
    && run?.status === 'done'
    && evidence
    && evidence.run_id === run.run_id
    && Number(evidence.epoch) === Number(run.epoch)
    && Number(evidence.candidate_revision) === Number(candidate.revision)
    && evidence.candidate_base_hash === candidate.base_hash
    && evidence.app_mode === appMode
    && evidence.assertion === COMPLETION_ASSERTION
    && contractEvidenceIsComplete
  )
}

export function workflowContractReportPresentation(candidate) {
  const report = candidate?.contract_report
  if (!report || !Array.isArray(report.checks)) {
    return {
      visible: false,
      level: 'unavailable',
      summary: { satisfied: 0, missing: 0, conflict: 0, unverified: 0 },
      issues: [],
    }
  }
  const summary = Object.fromEntries(
    ['satisfied', 'missing', 'conflict', 'unverified']
      .map(status => [status, Math.max(0, Number(report.summary?.[status]) || 0)]),
  )
  return {
    visible: true,
    level: report.passed ? (summary.unverified > 0 ? 'partially_verified' : 'verified') : 'blocked',
    summary,
    issues: report.checks.filter(check => check?.status !== 'satisfied'),
  }
}

export function workflowAssistApplyPresentation(candidate, appMode, applying = false) {
  const eligible = canApplyWorkflowAssistCandidate(candidate, appMode)
  return {
    eligible,
    visible: eligible || applying,
    disabled: applying || !eligible,
  }
}

export async function applyWorkflowAssistCandidate({
  appId,
  conversationId,
  candidate,
  appMode,
  syncDraftIfDirty,
  postApply,
  reconcile = () => {},
  onConflict = async () => {},
  isApplying = () => false,
  setApplying = () => {},
}) {
  if (isApplying())
    return { applied: false, conflict: false, skipped: true, candidate }
  if (!canApplyWorkflowAssistCandidate(candidate, appMode))
    return { applied: false, conflict: false, candidate }

  setApplying(true)
  try {
    const hash = synchronizedHash(await syncDraftIfDirty())
    if (!SHA256_PATTERN.test(hash))
      throw new TypeError('draft synchronization must return a lowercase SHA-256 hash')
    const response = await postApply(appId, {
      conversation_id: conversationId,
      hash,
    })
    return {
      applied: true,
      graph: candidate.graph,
      hash: response?.hash || hash,
    }
  }
  catch (error) {
    if (error?.response?.status !== 409)
      throw error
    const facts = {
      conversation_id: conversationId,
      ...(error.response.data || {}),
    }
    reconcile(facts)
    await onConflict(facts)
    return { applied: false, conflict: true, candidate }
  }
  finally {
    setApplying(false)
  }
}
