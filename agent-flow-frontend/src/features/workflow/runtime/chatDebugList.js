/**
 * Pure helpers for Chatflow debug bubble list.
 * Contrasts Dify debug-and-preview chatList (user + streaming assistant turns).
 */

/**
 * @typedef {{
 *   id: string,
 *   role: 'user' | 'assistant',
 *   content: string,
 *   status?: string,
 *   error?: string,
 *   citation?: object[],
 *   message_files?: object[],
 * }} ChatMessage
 */

/**
 * @param {ChatMessage[]} list
 * @param {string} query
 * @param {object[]} [messageFiles]
 * @returns {ChatMessage[]}
 */
export function appendChatTurn(list, query, messageFiles = []) {
  const ts = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  const files = Array.isArray(messageFiles) ? messageFiles.filter(Boolean) : []
  return [
    ...list,
    {
      id: `user-${ts}`,
      role: 'user',
      content: String(query || '').trim(),
      message_files: files,
    },
    {
      id: `assistant-${ts}`,
      role: 'assistant',
      content: '',
      status: 'streaming',
      citation: [],
      message_files: [],
    },
  ]
}

/**
 * @param {ChatMessage[]} list
 * @param {{
 *   content?: string,
 *   status?: string,
 *   error?: string,
 *   citation?: object[],
 *   message_files?: object[],
 * }} patch
 * @returns {ChatMessage[]}
 */
export function updateLastAssistant(list, patch = {}) {
  if (!list.length)
    return list
  const last = list[list.length - 1]
  if (last.role !== 'assistant')
    return list
  const next = list.slice()
  next[next.length - 1] = {
    ...last,
    ...(patch.content != null ? { content: patch.content } : {}),
    ...(patch.status != null ? { status: patch.status } : {}),
    ...(patch.error != null ? { error: patch.error } : {}),
    ...(patch.citation != null ? { citation: patch.citation } : {}),
    ...(patch.message_files != null ? { message_files: patch.message_files } : {}),
  }
  return next
}

/**
 * @returns {ChatMessage[]}
 */
export function clearChatList() {
  return []
}
