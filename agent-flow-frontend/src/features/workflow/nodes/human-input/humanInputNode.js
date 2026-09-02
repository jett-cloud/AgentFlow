export const HUMAN_INPUT_DEFAULTS = Object.freeze({
  delivery_methods: [], user_actions: [], form_content: '', inputs: [], timeout: 3, timeout_unit: 'day',
})

const LEGACY_DELIVERY_TYPES = { web_app: 'webapp', webapp: 'webapp', email: 'email' }

export function normalizeHumanInputData(data = {}) {
  const rawDelivery = Array.isArray(data.delivery_methods) ? data.delivery_methods : []
  const deliveryMethods = rawDelivery.map((item, index) => {
    if (typeof item === 'string') {
      const type = LEGACY_DELIVERY_TYPES[item] || item
      return { id: `delivery-${type}-${index}`, type, enabled: true }
    }
    return { ...item, id: String(item.id || `delivery-${item.type}-${index}`), enabled: item.enabled !== false }
  })
  const normalized = {
    ...data,
    delivery_methods: deliveryMethods,
    user_actions: Array.isArray(data.user_actions) ? data.user_actions.map(item => ({ ...item, id: String(item.id || ''), title: String(item.title || ''), button_style: item.button_style || 'default' })) : [],
    form_content: String(data.form_content ?? data.prompt ?? ''),
    inputs: Array.isArray(data.inputs) ? data.inputs.map(item => ({ ...item })) : [],
    timeout: Number(data.timeout) || 3,
    timeout_unit: data.timeout_unit === 'hour' ? 'hour' : 'day',
  }
  delete normalized.prompt
  delete normalized.form_inputs
  return normalized
}

export function isHumanInputDeliveryValid(method = {}) {
  if (!method.enabled) return true
  if (method.type !== 'email') return true
  const config = method.config
  return Boolean(config?.subject?.trim() && config?.body?.includes('{{#url#}}') && (config?.recipients?.whole_workspace || config?.recipients?.items?.length))
}
