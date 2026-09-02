export function getNodeErrorStrategy(data = {}) {
  return data.error_strategy || data.error_handle_mode || data.errorStrategy || 'none'
}

export function updateNodeErrorStrategy(data = {}, strategy = 'none') {
  return {
    ...data,
    error_strategy: strategy,
  }
}
