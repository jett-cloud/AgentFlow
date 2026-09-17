export function extractInstallTaskId(result) {
  return result?.task_id
    || result?.data?.task_id
    || result?.task?.task_id
    || result?.data?.task?.task_id
    || ''
}

export async function waitForPluginInstallTask(
  fetchTask,
  taskId,
  { maxAttempts = 90, intervalMs = 2000 } = {},
) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const payload = await fetchTask(taskId)
    const task = payload?.task || payload?.data?.task || payload
    const status = String(task?.status || '').toLowerCase()
    if (status === 'success')
      return task
    if (status === 'failed') {
      const failed = (task?.plugins || []).find(
        item => String(item?.status || '').toLowerCase() === 'failed',
      )
      throw new Error(failed?.message || '插件安装失败')
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs))
  }
  throw new Error('插件安装超时，请稍后点「刷新」')
}

export function isAuthorizationError(error) {
  if ([401, 403].includes(error?.response?.status))
    return true

  const message = typeof error === 'string'
    ? error
    : error?.response?.data?.message || error?.message || ''
  return /(unauthori[sz]ed|forbidden|missing (?:tool )?credentials?|credentials? (?:is|are) (?:missing|required)|api[_ -]?key|凭证|授权|未认证|无权)/i.test(message)
}
