import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { createServer } from 'node:http'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { chromium } from 'playwright'
import { createServer as createViteServer } from 'vite'

const projectRoot = fileURLToPath(new URL('../../../..', import.meta.url))

test('execution consent control defaults to ask, persists changes, and follows disabled state', async t => {
  let vite
  const server = createServer((request, response) => {
    if (request.url === '/favicon.ico') {
      response.writeHead(204)
      response.end()
      return
    }
    if (request.url === '/' || request.url === '/index.html') {
      vite.transformIndexHtml('/', `<!doctype html>
        <html>
          <body>
            <div id="app"></div>
            <script type="module" src="/src/features/workflow/assistant/__fixtures__/assistComposerConsentFixture.js"></script>
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
  vite = await createViteServer({
    configFile: false,
    root: projectRoot,
    appType: 'custom',
    plugins: [vue()],
    resolve: { alias: { '@': `${projectRoot}/src` } },
    server: { middlewareMode: true, hmr: { server } },
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
  await page.goto(`http://127.0.0.1:${address.port}/`)

  const select = page.getByRole('combobox', { name: 'Real calls' })
  await select.waitFor({ timeout: 5000 })
  assert.equal(await select.inputValue(), 'always_ask')
  assert.deepEqual(await select.locator('option').allTextContents(), ['Always ask', 'Always run'])
  assert.equal(await select.getAttribute('title'), 'Whether test runs may call real models and tools. Always ask requests approval before each metered run.')

  await select.selectOption('always_execute')
  assert.equal(await page.locator('#stored-consent-mode').textContent(), 'always_execute')

  await page.locator('#disable-composer').click()
  assert.equal(await select.isDisabled(), true)

  await page.reload()
  assert.equal(await page.getByRole('combobox', { name: 'Real calls' }).inputValue(), 'always_execute')
})
