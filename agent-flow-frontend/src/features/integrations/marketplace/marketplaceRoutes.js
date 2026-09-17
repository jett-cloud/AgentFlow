export const MARKETPLACE_ROUTES = {
  tools: '/integrations/marketplace/tools',
  models: '/integrations/marketplace/models',
}

export function marketplaceDetailPath(kind, org, name) {
  const base = kind === 'model' ? MARKETPLACE_ROUTES.models : MARKETPLACE_ROUTES.tools
  return `${base}/${encodeURIComponent(org)}/${encodeURIComponent(name)}`
}

export function integrationsTabPath(tab) {
  return `/integrations?tab=${tab === 'tools' ? 'tools' : 'models'}`
}
