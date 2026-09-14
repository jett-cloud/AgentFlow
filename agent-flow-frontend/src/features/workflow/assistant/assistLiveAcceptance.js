export function liveAcceptanceApproval(answers, questions) {
  const question = questions?.find(item => item?.id === 'live_run_consent' && item.kind === 'live_acceptance')
  const answer = answers?.find(item => item?.question_id === question?.id)
  const id = question?.execution_request?.request_id
  return answer?.approved === true && typeof id === 'string' && /^[a-f0-9]{32}$/.test(id) ? id : undefined
}
