export function createAssistComposerSubmission({ readText, readReferences, clearText, emitSend }) {
  function submit() {
    const message = String(readText() || '').trim()
    if (!message)
      return false
    const rawReferences = readReferences?.()
    const references = Array.isArray(rawReferences) ? rawReferences : []
    emitSend(message, {
      accepted() {
        if (String(readText() || '').trim() !== message)
          return false
        clearText()
        return true
      },
    }, references)
    return true
  }

  return { submit }
}
