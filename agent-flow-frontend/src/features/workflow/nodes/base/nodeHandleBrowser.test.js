import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { createServer } from 'node:http'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { chromium } from 'playwright'
import { createServer as createViteServer } from 'vite'

const projectRoot = fileURLToPath(new URL('../../../../..', import.meta.url))

test('a visible add affordance preserves drag-to-connect and keyboard activation', async t => {
  const vite = await createViteServer({
    configFile: false,
    root: projectRoot,
    appType: 'custom',
    plugins: [vue()],
    resolve: {
      alias: {
        '@': `${projectRoot}/src`,
      },
    },
    server: { middlewareMode: true },
  })
  const server = createServer((request, response) => {
    if (request.url === '/favicon.ico') {
      response.writeHead(204)
      response.end()
      return
    }
    if (request.url === '/' || request.url === '/index.html') {
      vite.transformIndexHtml('/', `<!doctype html>
        <html>
          <body style="margin:0">
            <div id="app"></div>
            <script type="module" src="/src/features/workflow/nodes/base/__fixtures__/nodeHandleBrowserFixture.js"></script>
          </body>
        </html>`).then(html => {
        response.writeHead(200, { 'Content-Type': 'text/html' })
        response.end(html)
      })
      return
    }
    vite.middlewares(request, response, () => {
      response.statusCode = 404
      response.end('not found')
    })
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))

  let browser
  t.after(async () => {
    await browser?.close()
    await new Promise(resolve => server.close(resolve))
    await vite.close()
  })
  const bundledChromium = chromium.executablePath()
  browser = await chromium.launch({
    ...(existsSync(bundledChromium) ? { executablePath: bundledChromium } : { channel: 'chrome' }),
    headless: true,
  })

  const address = server.address()
  const page = await browser.newPage()
  const browserErrors = []
  page.on('console', message => {
    if (message.type() === 'error')
      browserErrors.push(message.text())
  })
  page.on('pageerror', error => browserErrors.push(error.message))
  await page.goto(`http://127.0.0.1:${address.port}/`)

  const sourceHandle = page.locator('.vue-flow__node[data-id="source-node"] .node-handle-core')
  const targetHandle = page.locator('.vue-flow__node[data-id="target-node"] .node-handle-core')
  await sourceHandle.waitFor()
  await targetHandle.waitFor()

  const sourceBox = await sourceHandle.boundingBox()
  const targetBox = await targetHandle.boundingBox()
  assert.ok(sourceBox)
  assert.ok(targetBox)

  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, { steps: 8 })
  await page.mouse.up()

  await assert.doesNotReject(() => page.locator('#edge-count').waitFor({ state: 'visible' }))
  assert.equal(await page.locator('#edge-count').textContent(), '1')
  assert.equal(await page.locator('#selector-count').textContent(), '0')

  const addButton = page.getByRole('button', { name: '添加后续节点' })
  await addButton.focus()
  await addButton.press('Enter')
  assert.equal(await page.locator('#selector-count').textContent(), '1')
  assert.deepEqual(browserErrors, [])
})
