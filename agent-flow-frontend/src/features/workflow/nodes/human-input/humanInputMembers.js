export function filterWorkspaceMembers(members = [], query = '') {
  const needle = String(query || '').trim().toLowerCase()
  if (!needle)
    return [...members]
  return members.filter(member => (
    String(member.name || '').toLowerCase().includes(needle)
    || String(member.email || '').toLowerCase().includes(needle)
  ))
}

export function selectedMemberIds(items = []) {
  return [...new Set(
    (Array.isArray(items) ? items : [])
      .filter(item => item?.type === 'member' && item.reference_id)
      .map(item => String(item.reference_id)),
  )]
}

export function memberSelectorOptions(members = [], selectedIds = []) {
  const byId = new Map(members.map(member => [String(member.id), member]))
  const extras = selectedIds
    .map(id => String(id))
    .filter(id => id && !byId.has(id))
    .map(id => ({ id, name: id, email: '', unknown: true }))
  return [...members, ...extras]
}

export function replaceMemberRecipients(items = [], selectedIds = []) {
  const externals = (Array.isArray(items) ? items : []).filter(item => item?.type === 'external')
  const members = [...new Set((Array.isArray(selectedIds) ? selectedIds : []).filter(Boolean).map(id => String(id)))]
    .map(reference_id => ({ type: 'member', reference_id }))
  return [...members, ...externals]
}
