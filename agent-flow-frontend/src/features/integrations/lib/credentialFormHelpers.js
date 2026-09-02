/**
 * Shared credential_form_schemas helpers for model + tool auth UIs.
 * Aligns with official web model-modal Form type handling for high-frequency fields.
 */

import { i18nText } from './modelProviderHelpers.js'

export const CREDENTIAL_FIELD_TYPES = {
  textInput: 'text-input',
  secretInput: 'secret-input',
  numberInput: 'number-input',
  select: 'select',
  radio: 'radio',
  checkbox: 'checkbox',
  boolean: 'boolean',
}

/**
 * @param {unknown} schemas
 * @returns {Array<object>}
 */
export function normalizeCredentialFormFields(schemas) {
  const list = Array.isArray(schemas)
    ? schemas
    : (schemas?.credentials_schema
      || schemas?.credential_form_schemas
      || schemas?.schema
      || schemas?.data
      || [])

  return (list || []).map((schema) => {
    if (!schema || typeof schema !== 'object')
      return null
    const variable = String(schema.variable || schema.name || '').trim()
    if (!variable)
      return null

    const type = String(schema.type || CREDENTIAL_FIELD_TYPES.textInput)
    const options = Array.isArray(schema.options)
      ? schema.options.map(normalizeOption).filter(Boolean)
      : []

    return {
      variable,
      label: i18nText(schema.label, variable),
      type,
      placeholder: i18nText(schema.placeholder, ''),
      required: !!schema.required,
      default: schema.default !== undefined && schema.default !== null
        ? schema.default
        : undefined,
      options,
      show_on: Array.isArray(schema.show_on) ? schema.show_on : [],
      min: schema.min,
      max: schema.max,
      secret: type === CREDENTIAL_FIELD_TYPES.secretInput || type === 'secret',
    }
  }).filter(Boolean)
}

/**
 * @param {unknown} option
 */
function normalizeOption(option) {
  if (!option || typeof option !== 'object')
    return null
  const value = option.value
  if (value === undefined || value === null)
    return null
  return {
    value: String(value),
    label: i18nText(option.label, String(value)),
    show_on: Array.isArray(option.show_on) ? option.show_on : [],
  }
}

/**
 * @param {Array<{ variable: string, value: any }>} showOn
 * @param {Record<string, any>} values
 */
export function matchesShowOn(showOn, values = {}) {
  if (!Array.isArray(showOn) || !showOn.length)
    return true
  return showOn.every((rule) => {
    if (!rule || typeof rule !== 'object')
      return true
    const key = rule.variable
    if (!key)
      return true
    return String(values[key] ?? '') === String(rule.value ?? '')
  })
}

/**
 * @param {object[]} fields
 * @param {Record<string, any>} values
 */
export function getVisibleCredentialFields(fields, values = {}) {
  return (Array.isArray(fields) ? fields : []).filter(field => matchesShowOn(field.show_on, values))
}

/**
 * Options visible for the current form values.
 * @param {object} field
 * @param {Record<string, any>} values
 */
export function getVisibleOptions(field, values = {}) {
  return (field?.options || []).filter(option => matchesShowOn(option.show_on, values))
}

/**
 * @param {object} field
 */
export function getFieldDefaultValue(field) {
  if (!field)
    return ''
  if (field.default !== undefined)
    return coerceFieldValue(field, field.default)

  if (field.type === CREDENTIAL_FIELD_TYPES.radio || field.type === CREDENTIAL_FIELD_TYPES.select) {
    const first = field.options?.[0]?.value
    return first !== undefined ? String(first) : ''
  }
  if (field.type === CREDENTIAL_FIELD_TYPES.checkbox || field.type === CREDENTIAL_FIELD_TYPES.boolean)
    return false
  return ''
}

/**
 * @param {object} field
 * @param {unknown} value
 */
export function coerceFieldValue(field, value) {
  if (field?.type === CREDENTIAL_FIELD_TYPES.checkbox || field?.type === CREDENTIAL_FIELD_TYPES.boolean) {
    if (typeof value === 'boolean')
      return value
    if (value === 'true' || value === true)
      return true
    if (value === 'false' || value === false)
      return false
    return Boolean(value)
  }
  if (value === undefined || value === null)
    return ''
  return String(value)
}

/**
 * @param {object[]} fields
 * @returns {Record<string, any>}
 */
export function buildInitialCredentialFormValues(fields) {
  const values = {}
  for (const field of Array.isArray(fields) ? fields : [])
    values[field.variable] = getFieldDefaultValue(field)
  return values
}

/**
 * @param {object} field
 * @param {unknown} value
 * @param {Record<string, any>} allValues
 */
export function isValidOptionValue(field, value, allValues = {}) {
  if (!field || (field.type !== CREDENTIAL_FIELD_TYPES.radio && field.type !== CREDENTIAL_FIELD_TYPES.select))
    return true
  const options = getVisibleOptions(field, allValues)
  if (!options.length)
    return value === undefined || value === null || value === ''
  return options.some(option => option.value === String(value ?? ''))
}

/**
 * Build credentials payload for validate/save.
 * @param {object[]} fields
 * @param {Record<string, any>} values
 * @param {{ editing?: boolean }} [options]
 */
export function buildCredentialsPayload(fields, values = {}, options = {}) {
  const editing = !!options.editing
  const visible = getVisibleCredentialFields(fields, values)
  const credentials = {}

  for (const field of visible) {
    const raw = values[field.variable]
    if (field.type === CREDENTIAL_FIELD_TYPES.checkbox || field.type === CREDENTIAL_FIELD_TYPES.boolean) {
      credentials[field.variable] = coerceFieldValue(field, raw)
      continue
    }

    const value = String(raw ?? '').trim()
    if (!value) {
      if (field.required && !editing)
        throw new Error(`请填写 ${field.label}`)
      continue
    }

    if (!isValidOptionValue(field, value, values)) {
      const allowed = getVisibleOptions(field, values).map(item => item.value).join(', ')
      throw new Error(`${field.label} 的值无效，请选择：${allowed || '合法选项'}`)
    }

    credentials[field.variable] = value
  }

  return credentials
}
