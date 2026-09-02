const MAX_SVG_BYTES = 256 * 1024
const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const SUPPORTED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/svg+xml'])
const UNSAFE_ELEMENT = /<(?:script|style|foreignObject|iframe|object|embed|audio|video)\b/i
const EVENT_ATTRIBUTE = /\son[a-z]+\s*=/i
const EXTERNAL_REFERENCE = /\s(?:href|xlink:href)\s*=\s*["'](?!#)[^"']+["']/i
const EXTERNAL_CSS_URL = /url\(\s*["']?(?!#)[^)]+\)/i

export function sanitizeSvgMarkup(markup) {
  const source = String(markup || '').trim().replace(/<!--[\s\S]*?-->/g, '')
  if (!/^<svg\b/i.test(source) || !/<\/svg>\s*$/i.test(source))
    throw new Error('请选择有效的 SVG 文件')
  if (UNSAFE_ELEMENT.test(source) || EVENT_ATTRIBUTE.test(source) || EXTERNAL_REFERENCE.test(source) || EXTERNAL_CSS_URL.test(source))
    throw new Error('SVG 包含不安全或外部引用内容')
  return source
}

export function validateAppIconFile(file) {
  if (!file || !SUPPORTED_IMAGE_TYPES.has(file.type))
    throw new Error('请选择 PNG、JPG、WebP 或 SVG 图片')
  if (file.size > MAX_IMAGE_BYTES)
    throw new Error('图片文件不能超过 5 MB')
  if (file.type === 'image/svg+xml' && file.size > MAX_SVG_BYTES)
    throw new Error('SVG 文件不能超过 256 KB')
}

export function calculateSquareCrop({ width, height, frameSize, zoom, offsetX, offsetY }) {
  const scale = Math.max(frameSize / width, frameSize / height) * zoom
  const size = frameSize / scale
  return {
    sx: (width - size) / 2 - offsetX / scale,
    sy: (height - size) / 2 - offsetY / scale,
    size,
  }
}

export function clampCropOffset({ width, height, frameSize, zoom, offsetX, offsetY }) {
  const scale = Math.max(frameSize / width, frameSize / height) * zoom
  const maxX = Math.max(0, (width * scale - frameSize) / 2)
  const maxY = Math.max(0, (height * scale - frameSize) / 2)
  return {
    x: Math.max(-maxX, Math.min(maxX, offsetX)),
    y: Math.max(-maxY, Math.min(maxY, offsetY)),
    displayWidth: width * scale,
    displayHeight: height * scale,
  }
}

export async function createAppIconSource(file) {
  validateAppIconFile(file)
  if (file.type !== 'image/svg+xml')
    return URL.createObjectURL(file)
  const markup = sanitizeSvgMarkup(await file.text())
  return URL.createObjectURL(new Blob([markup], { type: 'image/svg+xml' }))
}

export async function cropImageToPng(image, crop, fileName, size = 256) {
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const context = canvas.getContext('2d')
  if (!context)
    throw new Error('当前浏览器无法裁剪图片')
  context.drawImage(image, crop.sx, crop.sy, crop.size, crop.size, 0, 0, size, size)
  const png = await canvasToBlob(canvas)
  const baseName = String(fileName || 'app-icon').replace(/\.[^.]+$/, '')
  return new File([png], `${baseName}.png`, { type: 'image/png' })
}

export async function svgFileToPng(file, size = 256) {
  if (!file || file.size > MAX_SVG_BYTES)
    throw new Error('SVG 文件不能超过 256 KB')

  const markup = sanitizeSvgMarkup(await file.text())
  const sourceUrl = URL.createObjectURL(new Blob([markup], { type: 'image/svg+xml' }))

  try {
    const image = await loadImage(sourceUrl)
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const context = canvas.getContext('2d')
    if (!context)
      throw new Error('当前浏览器无法转换 SVG')
    context.drawImage(image, 0, 0, size, size)
    const png = await canvasToBlob(canvas)
    const baseName = String(file.name || 'app-icon').replace(/\.svg$/i, '')
    return new File([png], `${baseName}.png`, { type: 'image/png' })
  }
  finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('无法读取这个 SVG 文件'))
    image.src = url
  })
}

function canvasToBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('SVG 转换失败')), 'image/png')
  })
}
