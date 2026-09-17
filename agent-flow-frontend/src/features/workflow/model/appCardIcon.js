const DEFAULT_INITIAL = 'A'
const INITIAL_BACKGROUNDS = Object.freeze([
  '#aeb5df',
  '#9fc8b9',
  '#ddb98f',
  '#c6a5d3',
  '#9fc3d8',
  '#dda6ad',
])

function appInitial(app) {
  const name = typeof app?.name === 'string' ? app.name.trim() : ''
  return name.slice(0, 1).toUpperCase() || DEFAULT_INITIAL
}

function appInitialBackground(app) {
  const name = typeof app?.name === 'string' ? app.name.trim() : ''
  let hash = 0
  for (const character of name)
    hash = ((hash * 31) + character.codePointAt(0)) >>> 0
  return INITIAL_BACKGROUNDS[hash % INITIAL_BACKGROUNDS.length]
}

export function resolveAppCardIcon(app) {
  if (app?.icon_type === 'image') {
    const previewUrl = typeof app.icon_url === 'string' ? app.icon_url.trim() : ''
    if (previewUrl)
      return { type: 'image', src: previewUrl }
  }

  return {
    type: 'initial',
    value: appInitial(app),
    background: appInitialBackground(app),
  }
}
