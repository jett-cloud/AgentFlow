/**
 * Browser-side Mermaid hydration for ```mermaid fenced blocks.
 * Keeps mermaid out of sync markdown helpers / node tests.
 */

let mermaidReady = null

async function ensureMermaid() {
  if (!mermaidReady) {
    mermaidReady = import('mermaid').then((mod) => {
      const mermaid = mod.default || mod
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'neutral',
      })
      return mermaid
    })
  }
  return mermaidReady
}

/**
 * Render all `.mermaid` nodes under root (idempotent via data-processed).
 * @param {ParentNode | null | undefined} root
 */
export async function hydrateMermaidDiagrams(root) {
  if (!root || typeof root.querySelectorAll !== 'function')
    return
  const nodes = [...root.querySelectorAll('pre.mermaid:not([data-processed])')]
  if (!nodes.length)
    return
  try {
    const mermaid = await ensureMermaid()
    await mermaid.run({ nodes })
  }
  catch {
    // Leave source pre visible if render fails.
  }
}
