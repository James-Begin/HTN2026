// Package the already-built static frontend as a portable, network-free HTML
// file. No backend, service worker, installed Node runtime, or local server is
// needed to OPEN the result. Build-time Node/dependencies are still required.
import { readFile, readdir, writeFile } from 'node:fs/promises'
import { resolve, sep, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const dist = fileURLToPath(new URL('../dist/', import.meta.url))
const root = resolve(dist)
const assets = await readdir(resolve(root, 'assets'))
if (assets.filter(name => name.endsWith('.js')).length !== 1) {
  throw new Error('Offline packaging expects a single JS bundle. Review dynamic chunks before shipping a backup.')
}
function assetPath(url) {
  if (!url.startsWith('/') || url.startsWith('//')) throw new Error(`Unexpected asset URL: ${url}`)
  const path = resolve(root, `.${url}`)
  if (!path.startsWith(root + sep)) throw new Error('Asset escaped the build directory')
  return path
}
async function dataUrl(url, mime) {
  return `data:${mime};base64,${(await readFile(assetPath(url))).toString('base64')}`
}
let html = await readFile(resolve(root, 'index.html'), 'utf8')
const scripts = [...html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"[^>]*><\/script>/g)]
if (scripts.length !== 1) throw new Error('Expected one entry script')
for (const [tag, url] of scripts) {
  // A data URL avoids an inline </script> sequence in saved source text ever
  // terminating the script tag, and works from a file:// URL in modern browsers.
  html = html.replace(tag, `<script type="module" src="${await dataUrl(url, 'text/javascript')}"></script>`)
}
for (const [tag, url] of html.matchAll(/<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g)) {
  let css = await readFile(assetPath(url), 'utf8')
  for (const [reference, raw] of [...css.matchAll(/url\(([^)]+)\)/g)]) {
    const asset = raw.trim().replace(/^["']|["']$/g, '')
    if (asset.startsWith('data:') || asset.startsWith('#')) continue
    const mime = { '.woff2': 'font/woff2', '.woff': 'font/woff', '.svg': 'image/svg+xml' }[extname(asset)]
    if (!mime) throw new Error(`Review unsupported offline asset: ${asset}`)
    css = css.replace(reference, `url("${await dataUrl(asset, mime)}")`)
  }
  html = html.replace(tag, `<style>${css}</style>`)
}
html = html.replace('href="/favicon.svg"', `href="${await dataUrl('/favicon.svg', 'image/svg+xml')}"`)
if (/<(?:script|link)\b[^>]*(?:src|href)="(?:\/|https?:)/i.test(html)) {
  throw new Error('Unbundled page resources remain in the offline document')
}
const output = resolve(root, 'claimtrace-offline.html')
await writeFile(output, html)
console.log(`Offline backup written: ${output}`)
