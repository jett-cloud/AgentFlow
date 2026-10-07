import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { chromium } from 'playwright'

const componentSource = readFileSync(new URL('./AssistLiveAcceptance.vue', import.meta.url), 'utf8')
const componentStyles = componentSource.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1]

async function launchBrowser(t) {
  try {
    return await chromium.launch({ headless: true })
  }
  catch {
    try {
      return await chromium.launch({ channel: 'chrome', headless: true })
    }
    catch {
      t.skip('No Chromium browser is available for the layout regression test')
      return null
    }
  }
}

test('live acceptance renders as a compact permission card with clear primary and secondary actions', async (t) => {
  assert.ok(componentStyles)
  const browser = await launchBrowser(t)
  if (!browser)
    return

  t.after(() => browser.close())
  const page = await browser.newPage()

  await page.setContent(`
    <style>${componentStyles}</style>
    <div style="width: 390px">
      <section class="live-acceptance">
        <div class="live-header">
          <div class="live-heading"><strong>允许真实运行？</strong><p>这次运行将调用真实模型和工具。</p></div>
        </div>
        <details class="live-budget"><summary>仅本次 · 最多 32 步 · 60 秒</summary></details>
        <div class="live-actions">
          <button class="live-secondary">改用模拟运行</button>
          <button class="live-primary">允许并真实运行</button>
        </div>
      </section>
    </div>
  `)

  const layout = await page.locator('.live-acceptance').evaluate((card) => {
    const primary = card.querySelector('.live-primary')
    const secondary = card.querySelector('.live-secondary')
    const actions = card.querySelector('.live-actions')
    return {
      cardClientWidth: card.clientWidth,
      cardScrollWidth: card.scrollWidth,
      cardRadius: getComputedStyle(card).borderRadius,
      actionsDisplay: getComputedStyle(actions).display,
      primaryBackground: getComputedStyle(primary).backgroundColor,
      primaryColor: getComputedStyle(primary).color,
      primaryHeight: primary.getBoundingClientRect().height,
      secondaryBackground: getComputedStyle(secondary).backgroundColor,
      secondaryHeight: secondary.getBoundingClientRect().height,
    }
  })

  assert.equal(layout.cardScrollWidth, layout.cardClientWidth)
  assert.equal(layout.cardRadius, '12px')
  assert.equal(layout.actionsDisplay, 'grid')
  assert.equal(layout.primaryBackground, 'rgb(23, 92, 211)')
  assert.equal(layout.primaryColor, 'rgb(255, 255, 255)')
  assert.ok(layout.primaryHeight >= 38)
  assert.equal(layout.secondaryBackground, 'rgb(255, 255, 255)')
  assert.ok(layout.secondaryHeight >= 38)
})
