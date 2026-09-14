import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('application shell exposes shared blue-white-gray design tokens', () => {
  const source = read('./App.vue')

  for (const token of [
    '--af-page',
    '--af-surface',
    '--af-text-primary',
    '--af-text-muted',
    '--af-border',
    '--af-brand',
    '--af-focus-ring',
    '--af-transition',
  ])
    assert.match(source, new RegExp(token))
})

test('three landing pages share the same product page heading structure', () => {
  const workflow = read('../features/workflow/pages/WorkflowPage.vue')
  const integrations = read('../features/integrations/pages/Integrations.vue')
  const datasets = read('../features/datasets/pages/DatasetListPage.vue')

  assert.match(workflow, /class="page-header"/)
  assert.match(workflow, /<h1>工作流编排<\/h1>/)
  assert.match(integrations, /class="page-header"/)
  assert.match(datasets, /class="page-header"/)
})
