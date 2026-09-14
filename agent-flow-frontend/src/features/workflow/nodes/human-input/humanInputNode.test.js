import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkflowChecklist } from '../../model/checklist.js'
import { flowToGraph, generateNewNode, graphToFlow } from '../../model/dsl.js'
import { getNodeOutputBranches } from '../../model/nodeHandleBranches.js'
import { getNodeOutputVars } from '../../model/variableOutputs.js'
import {
  HUMAN_INPUT_DEFAULTS,
  applyHumanInputActionIdInput,
  createHumanInputField,
  formatHumanInputOutputToken,
  getHumanInputFieldValidationErrors,
  mergeHumanInputPatch,
  normalizeHumanInputData,
  normalizeHumanInputField,
  removeHumanInputOutputToken,
  renameHumanInputOutputToken,
} from './humanInputNode.js'
import * as humanInput from './humanInputNode.js'

test('new human-input nodes use official empty defaults', () => {
  const { newNode } = generateNewNode({ type: 'human-input', id: 'human-1' })
  assert.deepEqual(newNode.data, { type: 'human-input', title: '人工介入', ...HUMAN_INPUT_DEFAULTS })
})

test('normalization migrates legacy delivery strings and preserves unknown fields', () => {
  const normalized = normalizeHumanInputData({ delivery_methods: ['web_app', 'email'], prompt: '确认', future: true })
  assert.deepEqual(normalized.delivery_methods.map(item => [item.type, item.enabled]), [['webapp', true], ['email', true]])
  assert.ok(normalized.delivery_methods.every(item => /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(item.id)))
  assert.equal(normalized.form_content, '确认')
  assert.equal(normalized.prompt, undefined)
  assert.equal(normalized.future, true)
})

test('normalization replaces invalid delivery ids and preserves valid UUIDs', () => {
  const validId = '6ba7b810-9dad-41d1-80b4-00c04fd430c8'
  const normalized = normalizeHumanInputData({
    delivery_methods: [
      { id: 'webapp', type: 'webapp', enabled: true },
      { id: validId, type: 'email', enabled: false },
    ],
  })

  assert.match(normalized.delivery_methods[0].id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
  assert.equal(normalized.delivery_methods[1].id, validId)
})

test('field factories emit only backend-supported Human Input shapes', () => {
  assert.deepEqual(humanInput.createHumanInputField?.('paragraph', 'comment'), {
    type: 'paragraph',
    output_variable_name: 'comment',
    default: { type: 'constant', selector: [], value: '' },
  })
  assert.deepEqual(humanInput.createHumanInputField?.('select', 'decision'), {
    type: 'select',
    output_variable_name: 'decision',
    option_source: { type: 'constant', selector: [], value: [] },
  })
  assert.deepEqual(humanInput.createHumanInputField?.('file-list', 'attachments'), {
    type: 'file-list',
    output_variable_name: 'attachments',
    allowed_file_extensions: [],
    allowed_file_types: ['image'],
    allowed_file_upload_methods: ['local_file', 'remote_url'],
    number_limits: 5,
  })
  assert.deepEqual(createHumanInputField('file', 'attachment'), {
    type: 'file',
    output_variable_name: 'attachment',
    allowed_file_extensions: [],
    allowed_file_types: ['image'],
    allowed_file_upload_methods: ['local_file', 'remote_url'],
  })
})

test('switching Human Input field types does not keep cross-type keys', () => {
  const fromParagraph = normalizeHumanInputField({
    ...createHumanInputField('paragraph', 'comment'),
    type: 'select',
  })
  assert.equal('default' in fromParagraph, false)
  assert.deepEqual(fromParagraph.option_source, { type: 'constant', selector: [], value: [] })

  const fromSelect = normalizeHumanInputField({
    ...createHumanInputField('select', 'comment'),
    type: 'file',
  })
  assert.equal('option_source' in fromSelect, false)
  assert.equal('number_limits' in fromSelect, false)
  assert.deepEqual(fromSelect.allowed_file_types, ['image'])

  const fromFileList = normalizeHumanInputField({
    ...createHumanInputField('file-list', 'comment'),
    type: 'paragraph',
  })
  assert.equal('allowed_file_types' in fromFileList, false)
  assert.equal('number_limits' in fromFileList, false)
  assert.deepEqual(fromFileList.default, { type: 'constant', selector: [], value: '' })
})

test('field validation reports empty, duplicate, reserved, and incomplete configs without mutating them', () => {
  const reserved = createHumanInputField('paragraph', '__action_id')
  const duplicate = [
    createHumanInputField('paragraph', 'comment'),
    createHumanInputField('paragraph', 'comment'),
  ]
  const missingSelector = {
    type: 'paragraph',
    output_variable_name: 'note',
    default: { type: 'variable', selector: [], value: '' },
  }
  const badSelect = {
    type: 'select',
    output_variable_name: 'decision',
    option_source: { type: 'constant', selector: [], value: 'not-an-array' },
  }
  const customFile = {
    type: 'file',
    output_variable_name: 'attachment',
    allowed_file_extensions: [],
    allowed_file_types: ['custom'],
    allowed_file_upload_methods: ['local_file'],
  }
  const negativeLimit = {
    type: 'file-list',
    output_variable_name: 'attachments',
    allowed_file_extensions: [],
    allowed_file_types: ['image'],
    allowed_file_upload_methods: ['local_file'],
    number_limits: -1,
  }

  const errors = getHumanInputFieldValidationErrors([
    createHumanInputField('paragraph', ''),
    ...duplicate,
    reserved,
    createHumanInputField('paragraph', '__action_value'),
    createHumanInputField('paragraph', '__rendered_content'),
    missingSelector,
    badSelect,
    customFile,
    negativeLimit,
  ])

  assert.ok(errors.some(item => item.includes('empty')))
  assert.ok(errors.some(item => item.includes('duplicate')))
  assert.ok(errors.some(item => item.includes('__action_id')))
  assert.ok(errors.some(item => item.includes('__action_value')))
  assert.ok(errors.some(item => item.includes('__rendered_content')))
  assert.ok(errors.some(item => item.includes('selector')))
  assert.ok(errors.some(item => item.includes('option')))
  assert.ok(errors.some(item => item.includes('extension')))
  assert.ok(errors.some(item => item.includes('number_limits') || item.includes('negative')))
  assert.deepEqual(normalizeHumanInputField(customFile).allowed_file_extensions, [])
  assert.equal(normalizeHumanInputField(negativeLimit).number_limits, -1)
})

test('Human Input output tokens format, rename, and remove exactly', () => {
  assert.equal(formatHumanInputOutputToken('comment'), '{{#$output.comment#}}')
  assert.equal(renameHumanInputOutputToken('A {{#$output.comment#}}', 'comment', 'note'), 'A {{#$output.note#}}')
  assert.equal(removeHumanInputOutputToken('A {{#$output.note#}} B', 'note'), 'A  B')
})

test('same-tick Human Input patches keep both inputs and form_content', () => {
  const current = normalizeHumanInputData({
    form_content: 'A {{#$output.comment#}}',
    inputs: [createHumanInputField('paragraph', 'comment')],
  })
  let pending = null
  pending = mergeHumanInputPatch(current, pending, { inputs: [createHumanInputField('paragraph', 'note')] })
  pending = mergeHumanInputPatch(current, pending, {
    form_content: renameHumanInputOutputToken(current.form_content, 'comment', 'note'),
  })
  assert.deepEqual(pending.inputs.map(item => item.output_variable_name), ['note'])
  assert.equal(pending.form_content, 'A {{#$output.note#}}')

  const lost = mergeHumanInputPatch(current, null, {
    form_content: renameHumanInputOutputToken(current.form_content, 'comment', 'note'),
  })
  assert.deepEqual(lost.inputs.map(item => item.output_variable_name), ['comment'])
})

test('illegal action id drafts stay local until a valid unique id is committed', () => {
  const illegal = applyHumanInputActionIdInput('1bad', ['approve'], 'approve')
  assert.equal(illegal.id, 'approve')
  assert.equal(illegal.display, '1bad')
  assert.equal(illegal.error, 'illegal action id')

  const committed = applyHumanInputActionIdInput('reject', ['approve'], 'approve')
  assert.equal(committed.id, 'reject')
  assert.equal(committed.display, 'reject')
  assert.equal(committed.error, '')
})

test('empty and whitespace action ids stay in draft and never replace the stored id', () => {
  for (const raw of ['', '   ']) {
    const result = applyHumanInputActionIdInput(raw, ['approve'], 'approve')
    assert.equal(result.id, 'approve')
    assert.equal(result.display, raw)
    assert.equal(result.error, 'empty action id')
  }
})

test('clearing a field name then typing a new one does not drop form_content tokens', () => {
  let stored = 'comment'
  let content = 'Please fill {{#$output.comment#}}'
  const typeName = (raw, others = []) => {
    const result = humanInput.applyHumanInputFieldNameInput(raw, others, stored)
    if (result.error)
      return result
    if (result.value !== stored)
      content = renameHumanInputOutputToken(content, stored, result.value)
    stored = result.value
    return result
  }

  assert.equal(typeName('', []).error, 'empty output variable name')
  assert.equal(stored, 'comment')
  assert.equal(content, 'Please fill {{#$output.comment#}}')

  assert.equal(typeName('   ', []).error, 'empty output variable name')
  assert.equal(stored, 'comment')
  assert.equal(content, 'Please fill {{#$output.comment#}}')

  assert.equal(typeName('__action_id', []).error.includes('reserved'), true)
  assert.equal(stored, 'comment')

  assert.equal(typeName('note', ['note']).error.includes('duplicate'), true)
  assert.equal(stored, 'comment')
  assert.equal(content, 'Please fill {{#$output.comment#}}')

  const committed = typeName('note', [])
  assert.equal(committed.error, '')
  assert.equal(stored, 'note')
  assert.equal(content, 'Please fill {{#$output.note#}}')
})

test('action id drafts are keyed by stored id so deleting an earlier action does not steal them', () => {
  const drafts = { approve: { display: '1bad' }, reject: { display: 'nope!' } }
  const remaining = ['reject']
  const next = humanInput.pruneHumanInputDrafts(drafts, remaining)
  assert.deepEqual(next, { reject: { display: 'nope!' } })
  assert.equal(humanInput.humanInputDraftKey('reject', 0), 'reject')
})

test('legacy Human Input fields migrate without leaking old or cross-type keys', () => {
  assert.deepEqual(humanInput.normalizeHumanInputField?.({
    type: 'files',
    output_variable_name: 'attachments',
    label: '附件',
    required: true,
    default_value: 'legacy',
    option_source: { type: 'constant', selector: [], value: ['bad'] },
  }), {
    type: 'file-list',
    output_variable_name: 'attachments',
    allowed_file_extensions: [],
    allowed_file_types: ['image'],
    allowed_file_upload_methods: ['local_file', 'remote_url'],
    number_limits: 5,
  })
})

test('legacy email recipients, prompt, and text fields migrate to the saved contract', () => {
  const legacy = {
    type: 'human-input',
    delivery_methods: [{
      id: 'not-a-uuid',
      type: 'email',
      enabled: true,
      config: {
        recipients: {
          whole_workspace: true,
          items: [{ type: 'member', user_id: 'member-1' }],
        },
        subject: 'Review',
        body: '{{#url#}}',
      },
    }],
    prompt: 'Legacy prompt',
    inputs: [{ type: 'text', output_variable_name: 'comment' }],
  }
  const once = normalizeHumanInputData(legacy)
  const serialized = JSON.stringify(once)

  assert.equal(once.form_content, 'Legacy prompt')
  assert.equal(once.prompt, undefined)
  assert.equal(once.inputs[0].type, 'paragraph')
  assert.match(once.delivery_methods[0].id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i)
  assert.deepEqual(once.delivery_methods[0].config.recipients, {
    include_bound_group: true,
    items: [{ type: 'member', reference_id: 'member-1' }],
  })
  assert.equal(serialized.includes('whole_workspace'), false)
  assert.equal(serialized.includes('user_id'), false)
  assert.equal(serialized.includes('"prompt"'), false)
  assert.equal(serialized.includes('"text"'), false)

  const twice = normalizeHumanInputData(once)
  assert.deepEqual(twice, once)
  assert.equal(twice.delivery_methods[0].id, once.delivery_methods[0].id)
})

test('actions and email recipients normalize to the backend contract', () => {
  assert.equal(humanInput.isHumanInputActionIdValid?.('approve_1'), true)
  assert.equal(humanInput.isHumanInputActionIdValid?.('_reject'), true)
  assert.equal(humanInput.isHumanInputActionIdValid?.('1approve'), false)
  assert.equal(humanInput.isHumanInputActionIdValid?.('has-dash'), false)
  assert.equal(humanInput.isHumanInputActionIdValid?.('a'.repeat(21)), false)
  assert.deepEqual(humanInput.HUMAN_INPUT_BUTTON_STYLES, ['primary', 'default', 'accent', 'ghost'])
  assert.deepEqual(humanInput.normalizeHumanInputEmailConfig?.({
    recipients: {
      whole_workspace: true,
      items: [
        { type: 'member', reference_id: 'member-1', user_id: 'must-not-leak' },
        { type: 'external', email: '  reviewer@example.com  ', label: 'must-not-leak' },
      ],
    },
    subject: '审批',
    body: '打开 {{#url#}}',
  }), {
    recipients: {
      include_bound_group: true,
      items: [
        { type: 'member', reference_id: 'member-1' },
        { type: 'external', email: 'reviewer@example.com' },
      ],
    },
    subject: '审批',
    body: '打开 {{#url#}}',
    debug_mode: false,
  })
  assert.deepEqual(humanInput.normalizeHumanInputEmailConfig?.(), {
    recipients: { include_bound_group: false, items: [] },
    subject: '',
    body: '请处理以下人工输入任务：\n\n{{#url#}}',
    debug_mode: false,
  })
})

test('actions expose exact Handles and form fields become outputs', () => {
  const data = normalizeHumanInputData({
    user_actions: [{ id: 'approve', title: '同意', button_style: 'primary' }],
    inputs: [{ type: 'paragraph', output_variable_name: 'comment', default: { type: 'constant', selector: [], value: '' } }],
  })
  assert.deepEqual(getNodeOutputBranches({ type: 'human-input', ...data }).map(branch => branch.id), ['approve', '__timeout'])
  const outputs = getNodeOutputVars({ data: { type: 'human-input', ...data } })
  assert.ok(outputs.some(item => item.variable === 'comment' && item.type === 'string'))
  assert.ok(outputs.some(item => item.variable === '__action_id'))
  assert.ok(outputs.some(item => item.variable === '__action_value'))
  assert.ok(outputs.some(item => item.variable === '__rendered_content'))
  assert.equal(outputs.some(item => item.variable === 'approve_approved'), false)
  assert.equal(outputs.some(item => item.variable === 'approve_comment'), false)
})

test('DSL round-trip and checklist reject missing delivery and actions', () => {
  const flow = graphToFlow({ nodes: [{ id: 'human-1', type: 'custom', data: { type: 'human-input', delivery_methods: [], user_actions: [], form_content: '', inputs: [], timeout: 3, timeout_unit: 'day', future: 1 } }], edges: [] })
  const exported = flowToGraph(flow.nodes, flow.edges)
  assert.equal(exported.nodes[0].data.future, 1)
  const issues = buildWorkflowChecklist({ nodes: [{ id: 'start', data: { type: 'start' } }, { id: 'human-1', data: exported.nodes[0].data }], edges: [{ source: 'start', target: 'human-1' }] })
  assert.ok(issues.some(issue => issue.id === 'human-delivery-human-1'))
  assert.ok(issues.some(issue => issue.id === 'human-actions-human-1'))
})

test('legacy Human Input DSL round-trip is idempotent and ignores conflicting _targetBranches', () => {
  const legacy = {
    nodes: [{
      id: 'human-1',
      type: 'custom',
      data: {
        type: 'human-input',
        delivery_methods: [{
          id: 'not-a-uuid',
          type: 'email',
          enabled: true,
          config: {
            recipients: { whole_workspace: true, items: [{ type: 'member', user_id: 'member-1' }] },
            subject: 'Review',
            body: '{{#url#}}',
          },
        }],
        prompt: 'Legacy prompt',
        inputs: [{ type: 'text', output_variable_name: 'comment' }],
        user_actions: [{ id: 'approve', title: '同意', button_style: 'primary' }],
        _targetBranches: [{ id: 'stale' }],
      },
    }],
    edges: [],
  }
  const once = flowToGraph(graphToFlow(legacy).nodes, graphToFlow(legacy).edges)
  const twice = flowToGraph(graphToFlow(once).nodes, graphToFlow(once).edges)
  const serialized = JSON.stringify(twice.nodes[0].data)
  assert.equal(twice.nodes[0].data.delivery_methods[0].id, once.nodes[0].data.delivery_methods[0].id)
  assert.deepEqual(twice.nodes[0].data.user_actions.map(item => item.id), ['approve'])
  assert.deepEqual(getNodeOutputBranches({ type: 'human-input', ...twice.nodes[0].data }).map(item => item.id), ['approve', '__timeout'])
  assert.equal(serialized.includes('whole_workspace'), false)
  assert.equal(serialized.includes('user_id'), false)
  assert.deepEqual(twice.nodes[0].data, once.nodes[0].data)
})

test('Human Input outputs include typed fields and special strings', () => {
  const outputs = getNodeOutputVars({
    data: {
      type: 'human-input',
      inputs: [
        { type: 'paragraph', output_variable_name: 'comment' },
        { type: 'select', output_variable_name: 'decision' },
        { type: 'file', output_variable_name: 'attachment' },
        { type: 'file-list', output_variable_name: 'attachments' },
      ],
    },
  })
  assert.deepEqual(
    outputs.filter(item => ['comment', 'decision', 'attachment', 'attachments', '__action_id', '__action_value', '__rendered_content'].includes(item.variable))
      .map(item => [item.variable, item.type]),
    [
      ['comment', 'string'],
      ['decision', 'string'],
      ['attachment', 'file'],
      ['attachments', 'arrayFile'],
      ['__action_id', 'string'],
      ['__action_value', 'string'],
      ['__rendered_content', 'string'],
    ],
  )
})
