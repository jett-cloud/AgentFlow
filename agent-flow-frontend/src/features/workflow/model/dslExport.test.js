import assert from 'node:assert/strict'
import test from 'node:test'
import {
  canExportWorkflowDsl,
  canContinueEditorDslExport,
  createSerialSaver,
  downloadWorkflowYaml,
  getWorkflowDslDownloadName,
  hasSecretEnvironmentVariables,
  resolveDslExportPlan,
  resolveSecretExportChoice,
} from './dslExport.js'

test('export is available only with the import/export DSL permission', () => {
  assert.equal(canExportWorkflowDsl([]), false)
  assert.equal(canExportWorkflowDsl(['app.acl.import_export_dsl']), true)
  assert.equal(canExportWorkflowDsl(['app.acl.delete']), false)
})

test('secret environment variables require an explicit export decision', () => {
  assert.equal(hasSecretEnvironmentVariables({
    environmentVariables: [{ name: 'API_KEY', value_type: 'secret' }],
  }), true)
  assert.equal(hasSecretEnvironmentVariables({
    environment_variables: [{ name: 'REGION', value_type: 'string' }],
  }), false)
  assert.equal(hasSecretEnvironmentVariables({
    workflow: {
      environment_variables: [{ name: 'NESTED_SECRET', value_type: 'secret' }],
    },
  }), true)
})

test('safe export response is reused unless the user explicitly includes secrets', () => {
  assert.equal(resolveDslExportPlan({ hasSecrets: false, secretChoice: null }), 'download-safe')
  assert.equal(resolveDslExportPlan({ hasSecrets: true, secretChoice: false }), 'download-safe')
  assert.equal(resolveDslExportPlan({ hasSecrets: true, secretChoice: true }), 'request-secrets')
  assert.equal(resolveDslExportPlan({ hasSecrets: true, secretChoice: null }), 'cancel')
})

test('secret export actions distinguish safe, sensitive, and cancelled outcomes', () => {
  assert.equal(resolveSecretExportChoice('safe'), false)
  assert.equal(resolveSecretExportChoice('include-secrets'), true)
  assert.equal(resolveSecretExportChoice('cancel'), null)
})

test('editor export stops when saving the current draft did not fully succeed', () => {
  assert.equal(canContinueEditorDslExport({ persistEditorDraft: true, draftSaved: false }), false)
  assert.equal(canContinueEditorDslExport({ persistEditorDraft: true, draftSaved: true }), true)
  assert.equal(canContinueEditorDslExport({ persistEditorDraft: false, draftSaved: false }), true)
})

test('editor export names the file from the current saved payload', () => {
  assert.equal(getWorkflowDslDownloadName({ payloadName: 'Renamed workflow', appName: 'Old name' }), 'Renamed workflow')
  assert.equal(getWorkflowDslDownloadName({ payloadName: '', appName: 'Old name' }), '')
  assert.equal(getWorkflowDslDownloadName({ payloadName: undefined, appName: 'Old name' }), 'Old name')
})

test('YAML download uses a safe filename, YAML MIME type, and cleans browser resources', () => {
  const calls = []
  const anchor = {
    click: () => calls.push('click'),
    remove: () => calls.push('remove'),
  }
  const documentImpl = {
    body: { append: child => calls.push(['append', child]) },
    createElement: tag => {
      assert.equal(tag, 'a')
      return anchor
    },
  }
  const urlImpl = {
    createObjectURL: blob => {
      calls.push(['blob', blob])
      return 'blob:workflow'
    },
    revokeObjectURL: url => calls.push(['revoke', url]),
  }
  class BlobImpl {
    constructor(parts, options) {
      this.parts = parts
      this.type = options.type
    }
  }

  downloadWorkflowYaml('version: 0.3.0', '', { documentImpl, urlImpl, BlobImpl })

  assert.equal(anchor.href, 'blob:workflow')
  assert.equal(anchor.download, 'workflow.yml')
  assert.deepEqual(calls[0][1], new BlobImpl(['version: 0.3.0'], { type: 'application/yaml' }))
  assert.deepEqual(calls.slice(1), [
    ['append', anchor],
    'click',
    'remove',
    ['revoke', 'blob:workflow'],
  ])
})

test('YAML download cleans its browser resources when append or click throws', () => {
  for (const failure of ['append', 'click']) {
    const calls = []
    const anchor = {
      click: () => {
        calls.push('click')
        if (failure === 'click') throw new Error('click failed')
      },
      remove: () => calls.push('remove'),
    }
    const documentImpl = {
      body: {
        append: () => {
          calls.push('append')
          if (failure === 'append') throw new Error('append failed')
        },
      },
      createElement: () => anchor,
    }
    const urlImpl = {
      createObjectURL: () => 'blob:workflow',
      revokeObjectURL: url => calls.push(['revoke', url]),
    }

    assert.throws(
      () => downloadWorkflowYaml('version: 0.3.0', 'Workflow', { documentImpl, urlImpl }),
      new RegExp(`${failure} failed`),
    )
    assert.deepEqual(calls.slice(-2), ['remove', ['revoke', 'blob:workflow']])
  }
})

test('serial saver waits for an in-flight autosave before saving a newer export payload', async () => {
  const calls = []
  let releaseOldSave
  const save = createSerialSaver(async (payload) => {
    calls.push(payload.name)
    if (payload.name === 'old draft')
      await new Promise((resolve) => { releaseOldSave = resolve })
    return true
  })

  const oldSave = save({ name: 'old draft' })
  const exportSave = save({ name: 'new export name' })
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(calls, ['old draft'])

  releaseOldSave()
  await Promise.all([oldSave, exportSave])
  assert.deepEqual(calls, ['old draft', 'new export name'])
})
