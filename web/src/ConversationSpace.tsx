import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { ArrowUpRight, Focus, Heart, Maximize2, Pause, Play, RotateCcw, Search } from 'lucide-react'
import artifact from '../../demo/recordings/conversation-space.json'
import type { GraphPost } from './graphData'
import './conversation-space.css'
import './conversation-space-overrides.css'

type Feature = { text: string; cosine: number; y: number | null; z: number | null; inputTruncated: boolean; estimated?: boolean }
type Layout = { referencePostId: string; referenceTextHash: string; basisId: string; features: Record<string, Feature> }
const layouts = artifact.layouts as Record<string, Layout>
const DAY = 86400000
const RADIUS = 22
const AXIS_LENGTH = 150
type TimeMode = 'flow' | 'elapsed'
type Display = { timeMode: TimeMode; cone: boolean; spread: number }
const stamp = (post: GraphPost) => Date.parse(post.publishedAt)
const order = (a: GraphPost, b: GraphPost) => stamp(a) - stamp(b) || a.id.localeCompare(b.id)
const authorName = (post: GraphPost) => post.author.replace(/\s*·\s*@\S+$/, '')
function liveFeature(post: GraphPost): Feature | undefined {
  if (![post.spaceScore, post.spaceY, post.spaceZ].every(value => typeof value === 'number' && Number.isFinite(value))) return undefined
  return { text: post.text, cosine: post.spaceScore!, y: post.spaceY!, z: post.spaceZ!, inputTruncated: false }
}

// A saved run can gain posts after its frozen MiniLM projection was recorded.
// Project their words through a stable signed hash so shared terms retain a
// shared direction until the live semantic projection replaces it. This avoids
// fabricating a single "waiting" rail at the bottom of the space.
const directionStopWords = new Set(['about', 'after', 'again', 'also', 'and', 'are', 'been', 'but', 'for', 'from', 'have', 'here', 'into', 'just', 'more', 'not', 'now', 'our', 'out', 'that', 'the', 'their', 'then', 'this', 'they', 'was', 'what', 'when', 'with', 'you', 'your'])
function stableHash(value: string, salt = 0) {
  let hash = 2166136261 ^ salt
  for (let index = 0; index < value.length; index++) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619)
  return hash >>> 0
}
function fallbackFeature(post: GraphPost): Feature | undefined {
  const words = (post.text.toLowerCase().match(/[\p{L}\p{N}_-]+/gu) || [])
    .filter(word => word.length > 2 && !directionStopWords.has(word)).slice(0, 90)
  let y = 0, z = 0
  for (const word of words) {
    const angle = stableHash(word) / 0xffffffff * Math.PI * 2
    y += Math.cos(angle); z += Math.sin(angle)
  }
  if (Math.hypot(y, z) < .001) {
    const angle = stableHash(post.id) / 0xffffffff * Math.PI * 2
    y = Math.cos(angle); z = Math.sin(angle)
  }
  const length = Math.hypot(y, z)
  const seedMatch = post.semanticScore ?? post.lexicalScore ?? post.rankingScore ?? 0
  const radius = .24 + .48 * (1 - Math.max(0, Math.min(1, seedMatch)))
  return { text: post.text, cosine: seedMatch, y: y / length * radius, z: z / length * radius, inputTruncated: false, estimated: true }
}
const dateLabel = (time: number) => new Date(time).toLocaleString('en-CA', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' })
function elapsed(ms: number) {
  const seconds = Math.floor(Math.abs(ms) / 1000)
  const days = Math.floor(Math.abs(ms) / DAY), hours = Math.floor(seconds / 3600) % 24
  const minutes = Math.floor(seconds / 60) % 60
  const parts = days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`
  return `${ms < 0 ? '−' : '+'}${parts}`
}

type Point = { post: GraphPost; position: THREE.Vector3; feature?: Feature; pending: boolean; estimated: boolean }
type HoveredPoint = { id: string; x: number; y: number }
type Frame = { origin: number; end: number; scale: number; times: number[]; flow: number[] }
function makeFrame(origin: number, end: number, posts: GraphPost[]): Frame {
  // Calibrate once against the reference capture, not the changing replay subset.
  // Identical timestamps stay coincident; no timestamps or filler posts are invented.
  const times = [...new Set([origin, end, ...posts.map(stamp).filter(Number.isFinite)])].sort((a, b) => a - b)
  const cumulative = [0]
  for (let i = 1; i < times.length; i++) cumulative.push(cumulative[i - 1] + .35 + Math.log1p((times[i] - times[i - 1]) / 30000))
  const zero = cumulative[times.indexOf(origin)]
  const length = cumulative[times.indexOf(end)] - zero
  return { origin, end, scale: AXIS_LENGTH / (end - origin), times, flow: cumulative.map(value => (value - zero) / length * AXIS_LENGTH) }
}
function interpolate(value: number, from: number[], to: number[]) {
  let low = 0, high = from.length - 1
  while (high - low > 1) {
    const middle = (low + high) >> 1
    if (from[middle] <= value) low = middle
    else high = middle
  }
  return to[low] + (value - from[low]) / (from[high] - from[low]) * (to[high] - to[low])
}
const timeX = (frame: Frame, time: number, mode: TimeMode) => mode === 'elapsed' ? (time - frame.origin) * frame.scale : interpolate(time, frame.times, frame.flow)
const timeAtX = (frame: Frame, x: number, mode: TimeMode) => mode === 'elapsed' ? frame.origin + x / frame.scale : interpolate(x, frame.flow, frame.times)
const radiusAt = (x: number, display: Display) => RADIUS * display.spread * (display.cone ? .25 + 1.65 * Math.min(1, Math.max(0, x / AXIS_LENGTH)) : 1)
type SceneAPI = { configure: (display: Display) => void; update: (points: Point[], selected: string, links: string) => void; focus: (id: string) => void; fit: () => void; reset: () => void; preset: (view: 'side' | 'end') => void; dispose: () => void; showGuides: () => void }

/** Frozen placement transforms; camera gestures never run a layout simulation. */
function createScene(host: HTMLDivElement, frame: Frame, seedId: string, initialDisplay: Display, onSelect: (id: string) => void, onHover: (hover: HoveredPoint | null) => void, cinematic: boolean, births: Map<string, number>): SceneAPI {
  let display = initialDisplay
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.8))
  renderer.setClearColor('#000000')
  renderer.outputColorSpace = THREE.SRGBColorSpace
  host.appendChild(renderer.domElement)
  renderer.domElement.setAttribute('aria-label', '3D conversation. Drag to orbit; scroll to zoom. Use the post list for keyboard selection.')
  renderer.domElement.setAttribute('role', 'img')
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(42, 1, .1, 5000)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = .12
  controls.minDistance = 3
  controls.maxDistance = 1600
  controls.maxPolarAngle = Math.PI * .94
  controls.minPolarAngle = Math.PI * .06
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  let raf: number | null = null
  let disposed = false
  let points: Point[] = []
  let idBySlot: string[] = []
  let nodes: THREE.InstancedMesh | null = null
  let capacity = 0
  let selected = seedId
  let hovered: string | null = null
  let signature = ''
  let initiallyFitted = false
  let cameraTouched = false
  let cinematicMode = cinematic
  let hideGuides = cinematic
  let cameraTween: { start: number; from: THREE.Vector3; to: THREE.Vector3; fromTarget: THREE.Vector3; toTarget: THREE.Vector3 } | null = null
  if (!births.has(seedId)) births.set(seedId, performance.now() - 4000)
  const dummy = new THREE.Object3D()
  const baseGeometry = new THREE.IcosahedronGeometry(1, 1)
  const baseMaterial = new THREE.MeshBasicMaterial({ color: '#ffffff' })
  const linksGeometry = new THREE.BufferGeometry()
  const linksMaterial = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: .38, depthWrite: false })
  const edgeLines = new THREE.LineSegments(linksGeometry, linksMaterial)
  scene.add(edgeLines)
  const guides = new THREE.Group()
  scene.add(guides)
  const ring = new THREE.Mesh(new THREE.TorusGeometry(.83, .025, 6, 48), new THREE.MeshBasicMaterial({ color: '#d7f4ff', depthTest: false }))
  ring.renderOrder = 5
  scene.add(ring)

  function invalidate() {
    if (!disposed && raf === null) raf = requestAnimationFrame(render)
  }
  function sizeLabels() {
    const height = Math.max(1, host.clientHeight)
    const scale = 32 * 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / height
    for (const child of guides.children) if (child instanceof THREE.Sprite) child.scale.set(scale * 512 / 80, scale, 1)
  }
  function label(text: string, x: number, y: number, z: number) {
    const canvas = document.createElement('canvas')
    canvas.width = 512; canvas.height = 80
    const context = canvas.getContext('2d')!
    context.font = '500 28px system-ui, sans-serif'
    const measuredWidth = context.measureText(text).width
    if (measuredWidth > 480) context.font = `500 ${28 * 480 / measuredWidth}px system-ui, sans-serif`
    context.fillStyle = '#8d9dab'
    context.textAlign = 'center'; context.fillText(text, 256, 48)
    const texture = new THREE.CanvasTexture(canvas)
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false, sizeAttenuation: false }))
    sprite.position.set(x, y, z)
    guides.add(sprite)
  }
  function guideLine(vertices: THREE.Vector3[], color: string, opacity: number) {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(vertices), new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false }))
    guides.add(line)
  }
  function drawGuides() {
    for (const child of [...guides.children]) {
      const item = child as THREE.Mesh
      item.geometry?.dispose()
      const material = item.material as THREE.SpriteMaterial
      material.map?.dispose(); material.dispose()
      guides.remove(child)
    }
    guideLine([new THREE.Vector3(-3, 0, 0), new THREE.Vector3(AXIS_LENGTH + 3, 0, 0)], '#7995ae', .65)
    // Longitudinal guides replace the daily-looking hoops. They are display
    // guides, not inferred branches or trajectories between unrelated posts.
    for (let spoke = 0; spoke < 4; spoke++) {
      const angle = Math.PI / 4 + spoke * Math.PI / 2
      guideLine(Array.from({ length: 41 }, (_, index) => {
        const x = AXIS_LENGTH * index / 40, radius = radiusAt(x, display) * .8
        return new THREE.Vector3(x, radius * Math.cos(angle), radius * Math.sin(angle))
      }), '#42667f', .16)
    }
    for (let tick = 0; tick <= 40; tick++) {
      const x = AXIS_LENGTH * tick / 40, major = tick % 5 === 0
      guideLine([new THREE.Vector3(x, -.5, 0), new THREE.Vector3(x, major ? -2 : -1.1, 0)], '#7696ae', major ? .6 : .3)
      // Three labels stay legible in the narrow mobile canvas; the shorter
      // unlabeled major ticks still convey the interval between them.
      if (tick % 20 === 0) {
        const y = -(radiusAt(x, display) * .8 + 4)
        label(tick === 0 ? 'REFERENCE · t = 0' : elapsed(timeAtX(frame, x, display.timeMode) - frame.origin), x, y, 0)
      }
    }
    label(display.timeMode === 'flow' ? 'PUBLICATION ORDER · GAPS COMPRESSED →' : 'ELAPSED PUBLICATION TIME →', AXIS_LENGTH * .55, -(radiusAt(AXIS_LENGTH * .55, display) * .8 + 20), 0)
    sizeLabels()
  }
  if (!hideGuides) drawGuides()

  function moveCamera(to: THREE.Vector3, target: THREE.Vector3) {
    if (reduced) { camera.position.copy(to); controls.target.copy(target); controls.update() }
    else cameraTween = { start: performance.now(), from: camera.position.clone(), to, fromTarget: controls.target.clone(), toTarget: target }
    invalidate()
  }
  function fit() {
    if (!points.length) return
    const bounds = new THREE.Box3().setFromPoints(points.map(point => point.position))
    const center = bounds.getCenter(new THREE.Vector3())
    const size = bounds.getSize(new THREE.Vector3())
    const tangent = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
    const distance = Math.max(25, size.x * .6 / (tangent * camera.aspect), size.y * .7 / tangent) + size.z * .5
    moveCamera(center.clone().add(new THREE.Vector3(.08, .30, 1).normalize().multiplyScalar(distance)), center)
  }
  function reset() { cameraTouched = false; fit() }
  function cloudFrame() {
    const bounds = new THREE.Box3().setFromPoints(points.map(point => point.position))
    const center = bounds.getCenter(new THREE.Vector3())
    const size = bounds.getSize(new THREE.Vector3())
    const span = Math.max(size.x, size.y * camera.aspect, size.z)
    const tangent = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
    const distance = Math.max(30, span * .7 / tangent)
    return { center, position: center.clone().add(new THREE.Vector3(0, .08, 1).normalize().multiplyScalar(distance)) }
  }
  if (cinematic) {
    camera.position.set(0, 0, 30); controls.target.set(0, 0, 0)
  } else {
    camera.position.set(49, 31, 94); controls.target.set(40, 0, 0)
  }
  controls.update()
  function updateMatrices(now: number) {
    if (!nodes) return false
    let animating = false
    const screenScale = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / Math.max(1, host.clientHeight)
    points.forEach((point, slot) => {
      const progress = reduced || point.post.id === seedId ? 1 : Math.min(1, (now - (births.get(point.post.id) ?? now)) / 320)
      if (progress < 1) animating = true
      const active = point.post.id === selected || point.post.id === hovered
      const size = point.post.id === seedId ? .55 : active ? .42 : .22 + Math.min(.15, Math.log1p(Math.max(0, point.post.likes ?? 0)) * .014)
      dummy.position.copy(point.position)
      const minSize = point.position.distanceTo(camera.position) * screenScale * (point.post.id === seedId ? 4 : active ? 3 : 1.5)
      dummy.scale.setScalar(Math.max(size, minSize) * Math.max(.05, progress))
      dummy.updateMatrix()
      nodes!.setMatrixAt(slot, dummy.matrix)
      const color = point.pending ? '#53606c' : point.estimated ? '#7895aa' : point.post.id === seedId ? '#f1faff' : active ? '#ffffff' : point.post.quotedPostId ? '#b8a0f4' : point.post.parentId ? '#72d3cf' : '#6da9d2'
      nodes!.setColorAt(slot, new THREE.Color(color))
    })
    nodes.instanceMatrix.needsUpdate = true
    if (nodes.instanceColor) nodes.instanceColor.needsUpdate = true
    const point = points.find(item => item.post.id === selected)
    ring.visible = !!point
    if (point) {
      ring.position.copy(point.position); ring.quaternion.copy(camera.quaternion)
      ring.scale.setScalar(Math.max(1, point.position.distanceTo(camera.position) * screenScale * 6 / .83))
    }
    return animating
  }
  let lastFrame = performance.now()
  function render(now: number) {
    raf = null
    if (disposed) return
    const dt = Math.min(.05, (now - lastFrame) / 1000)
    lastFrame = now
    if (cameraTween) {
      const t = Math.min(1, (now - cameraTween.start) / 850)
      const eased = 1 - (1 - t) ** 3
      camera.position.lerpVectors(cameraTween.from, cameraTween.to, eased)
      controls.target.lerpVectors(cameraTween.fromTarget, cameraTween.toTarget, eased)
      if (t === 1) cameraTween = null
    }
    let tracking = false
    if (points.length && !cameraTouched && !cameraTween) {
      const { position, center } = cloudFrame()
      const follow = reduced ? 1 : 1 - Math.exp((cinematicMode ? .85 : .45) * -dt)
      camera.position.lerp(position, follow)
      controls.target.lerp(center, follow)
      tracking = camera.position.distanceTo(position) > .08 || controls.target.distanceTo(center) > .08
    }
    const moving = controls.update()
    const animating = updateMatrices(now)
    renderer.render(scene, camera)
    if (moving || animating || cameraTween || tracking) invalidate()
  }
  controls.addEventListener('change', invalidate)
  controls.addEventListener('start', () => { cameraTween = null; cameraTouched = true })
  const resize = new ResizeObserver(() => {
    const { width, height } = host.getBoundingClientRect()
    if (!width || !height) return
    renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix()
    sizeLabels()
    invalidate()
  })
  resize.observe(host)
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  let down = { x: 0, y: 0 }
  let dragging = false
  function pick(event: PointerEvent) {
    if (!nodes) return null
    const bounds = renderer.domElement.getBoundingClientRect()
    pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, -(event.clientY - bounds.top) / bounds.height * 2 + 1)
    raycaster.setFromCamera(pointer, camera)
    const hit = raycaster.intersectObject(nodes)[0]
    if (hit?.instanceId !== undefined) return idBySlot[hit.instanceId]
    // A modest screen-space hit target keeps small glyphs usable without
    // inflating their visual size or moving their measured coordinates.
    let nearest: string | null = null, distance = 8
    for (const point of points) {
      const projected = point.position.clone().project(camera)
      if (projected.z < -1 || projected.z > 1) continue
      const x = bounds.left + (projected.x + 1) * bounds.width / 2
      const y = bounds.top + (1 - projected.y) * bounds.height / 2
      const d = Math.hypot(event.clientX - x, event.clientY - y)
      if (d < distance) { nearest = point.post.id; distance = d }
    }
    return nearest
  }
  function pointerDown(event: PointerEvent) { down = { x: event.clientX, y: event.clientY }; dragging = true }
  function pointerMove(event: PointerEvent) {
    if (dragging) return
    const id = pick(event)
    if (id !== hovered) {
      hovered = id
      const point = id ? points.find(item => item.post.id === id) : undefined
      if (point && id) {
        const projected = point.position.clone().project(camera)
        onHover({ id, x: Math.min(90, Math.max(10, (projected.x + 1) * 50)), y: Math.min(82, Math.max(15, (1 - projected.y) * 50)) })
      } else onHover(null)
      renderer.domElement.style.cursor = id ? 'pointer' : 'grab'; invalidate()
    }
  }
  function pointerUp(event: PointerEvent) {
    dragging = false
    if (event.button !== 0 || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) return
    const id = pick(event)
    if (id) onSelect(id)
  }
  function pointerLeave() { dragging = false; hovered = null; onHover(null); invalidate() }
  renderer.domElement.addEventListener('pointerdown', pointerDown)
  renderer.domElement.addEventListener('pointermove', pointerMove)
  renderer.domElement.addEventListener('pointerup', pointerUp)
  renderer.domElement.addEventListener('pointerleave', pointerLeave)
  const contextLost = (event: Event) => { event.preventDefault(); onHover(null) }
  renderer.domElement.addEventListener('webglcontextlost', contextLost)

  return {
    configure(nextDisplay) {
      if (display.timeMode === nextDisplay.timeMode && display.cone === nextDisplay.cone && display.spread === nextDisplay.spread) return
      display = nextDisplay
      if (!hideGuides) drawGuides()
      invalidate()
    },
    showGuides() {
      cinematicMode = false
      if (!hideGuides) return
      hideGuides = false
      initiallyFitted = true
      drawGuides()
      invalidate()
    },
    update(next, selection, linkMode) {
      const key = next.map(point => `${point.post.id}:${point.position.toArray().join(',')}`).join('|') + selection + linkMode
      if (key === signature) return
      signature = key; points = next; selected = selection
      const now = performance.now()
      for (const point of next) {
        if (births.has(point.post.id)) continue
        births.set(point.post.id, point.post.id === seedId ? now - 4000 : now)
      }
      if (!nodes || next.length > capacity) {
        if (nodes) { scene.remove(nodes); nodes.dispose() }
        capacity = Math.max(64, 2 ** Math.ceil(Math.log2(Math.max(1, next.length))))
        nodes = new THREE.InstancedMesh(baseGeometry, baseMaterial, capacity)
        nodes.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
        nodes.frustumCulled = false
        scene.add(nodes)
      }
      nodes.count = next.length
      idBySlot = next.map(point => point.post.id)
      updateMatrices(now)
      nodes.computeBoundingSphere()
      const byId = new Map(next.map(point => [point.post.id, point]))
      const vertices: number[] = [], colors: number[] = []
      if (linkMode !== 'none') for (const point of next) {
        for (const [type, id] of [['quote', point.post.quotedPostId], ['reply', point.post.parentId]] as const) {
          const target = id ? byId.get(id) : undefined
          if (!target || target === point || (linkMode === 'selected' && point.post.id !== selection && id !== selection)) continue
          const a = target.position, b = point.position
          const bend = 1.4 + Math.min(4, Math.abs(a.x - b.x) * .06)
          let hash = 0
          for (const char of point.post.id + id) hash = (hash * 31 + char.charCodeAt(0)) | 0
          const sign = hash % 2 ? 1 : -1
          const c1 = a.clone().lerp(b, .32).add(new THREE.Vector3(0, bend, sign * bend))
          const c2 = a.clone().lerp(b, .68).add(new THREE.Vector3(0, bend, sign * bend))
          const curve = new THREE.CubicBezierCurve3(a, c1, c2, b).getPoints(22)
          const color = new THREE.Color(type === 'quote' ? '#b69bee' : '#6bd4cb')
          for (let i = 0; i < curve.length - 1; i++) {
            vertices.push(...curve[i].toArray(), ...curve[i + 1].toArray())
            colors.push(color.r, color.g, color.b, color.r, color.g, color.b)
          }
        }
      }
      linksGeometry.dispose()
      linksGeometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
      linksGeometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
      linksGeometry.computeBoundingSphere()
      if (!cinematicMode && !cameraTouched && next.length && !initiallyFitted) {
        initiallyFitted = true
        fit()
      }
      invalidate()
    },
    focus(id) {
      const point = points.find(item => item.post.id === id)
      if (point) moveCamera(point.position.clone().add(new THREE.Vector3(8, 8, 23)), point.position.clone())
    },
    fit,
    reset,
    preset(view) {
      const center = controls.target.clone()
      moveCamera(center.clone().add(view === 'side' ? new THREE.Vector3(0, 0, Math.max(160, 180 / camera.aspect)) : new THREE.Vector3(-230, .01, 0)), center)
    },
    dispose() {
      disposed = true
      if (raf !== null) cancelAnimationFrame(raf)
      resize.disconnect(); controls.dispose()
      scene.traverse(object => {
        const item = object as THREE.Mesh
        if (item.geometry && item.geometry !== baseGeometry && item.geometry !== linksGeometry) item.geometry.dispose()
        const materials = item.material ? Array.isArray(item.material) ? item.material : [item.material] : []
        for (const material of materials) {
          if (material === baseMaterial || material === linksMaterial) continue
          const map = (material as THREE.SpriteMaterial).map
          map?.dispose(); material.dispose()
        }
      })
      baseGeometry.dispose(); baseMaterial.dispose(); linksGeometry.dispose(); linksMaterial.dispose(); nodes?.dispose()
      renderer.domElement.removeEventListener('webglcontextlost', contextLost)
      renderer.dispose(); renderer.domElement.remove()
    },
  }
}

export default function ConversationSpace({ posts, seedId, referencePosts, onOpenPost, compact = false, cinematic = false, onSelectPost }: {
  posts: GraphPost[]; seedId: string; referencePosts?: GraphPost[]; onOpenPost: (post: GraphPost) => void
  compact?: boolean; cinematic?: boolean; onSelectPost?: (post: GraphPost) => void
}) {
  const corpus = useMemo(() => [...new Map(posts.filter(post => Number.isFinite(stamp(post)) && post.id !== 'seed-text').map(post => [post.id, post])).values()].sort(order), [posts])
  const referenceCorpus = referencePosts?.length ? referencePosts : corpus
  const anchorId = useRef(seedId)
  if (!anchorId.current && referenceCorpus.length) anchorId.current = [...referenceCorpus].sort((a, b) => (b.likes ?? -1) - (a.likes ?? -1) || a.id.localeCompare(b.id))[0].id
  const reference = referenceCorpus.find(post => post.id === anchorId.current)
  const candidateLayout = reference ? layouts[reference.id] : undefined
  const layout = reference && candidateLayout?.features[reference.id]?.text === reference.text ? candidateLayout : undefined
  const [selectedId, setSelectedId] = useState(seedId)
  const [hovered, setHovered] = useState<HoveredPoint | null>(null)
  const [query, setQuery] = useState('')
  const [links, setLinks] = useState('selected')
  const [timeMode, setTimeMode] = useState<TimeMode>('flow')
  const [cone, setCone] = useState(true)
  const [spread, setSpread] = useState(1.2)
  const display = useMemo<Display>(() => ({ timeMode, cone, spread }), [timeMode, cone, spread])
  const [earlier, setEarlier] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [cursor, setCursor] = useState<number | null>(null)
  const [speed, setSpeed] = useState(1)
  const [showAllConnections, setShowAllConnections] = useState(false)
  const cursorRef = useRef(cursor)
  cursorRef.current = cursor
  const [failure, setFailure] = useState('')
  const host = useRef<HTMLDivElement>(null)
  const api = useRef<SceneAPI | null>(null)
  const cinematicRef = useRef(cinematic)
  cinematicRef.current = cinematic
  const nodeBirths = useRef(new Map<string, number>())
  const layoutFitKey = `${earlier}:${timeMode}:${cone}`
  const layoutFitKeyRef = useRef(layoutFitKey)
  const frameRef = useRef<{ id: string; frame: Frame } | null>(null)
  const maximum = Math.max(reference ? stamp(reference) : 0, ...referenceCorpus.map(stamp))
  if (reference && frameRef.current?.id !== reference.id) {
    const origin = stamp(reference)
    const end = origin + Math.max(3600000, (maximum - origin) * 1.05)
    frameRef.current = { id: reference.id, frame: makeFrame(origin, end, referenceCorpus) }
  }
  const frame = frameRef.current?.frame
  const start = frame ? earlier ? Math.min(frame.origin, ...referenceCorpus.map(stamp)) : frame.origin : 0
  const end = frame ? Math.max(frame.end, maximum) : 1
  const cutoff = cursor ?? end
  const selected = corpus.find(post => post.id === selectedId) || corpus.find(post => post.id === reference?.id) || corpus[0]
  const liveSpaceMethod = corpus.find(post => liveFeature(post))?.spaceMethod
  const activeId = selected?.id || ''
  const matchingFeature = (post: GraphPost) => {
    const feature = layout?.features[post.id]
    return feature?.text === post.text ? feature : liveFeature(post) || fallbackFeature(post)
  }
  const points = useMemo<Point[]>(() => !frame ? [] : corpus.filter(post => stamp(post) <= cutoff && (earlier || stamp(post) >= frame.origin)).map(post => {
    const matched = matchingFeature(post)
    const isReference = post.id === reference?.id
    // The reference is an actual coordinate-system origin, never an awaiting
    // embedding. This keeps it at t=0 even while the live projection arrives.
    const pending = !isReference && (matched?.y == null || matched.z == null)
    const x = isReference ? 0 : timeX(frame, stamp(post), timeMode)
    const radius = radiusAt(x, display)
    const y = isReference ? 0 : pending ? 0 : matched!.y! * radius
    const z = isReference || pending ? 0 : matched!.z! * radius
    return { post, feature: matched, pending, estimated: !!matched?.estimated, position: new THREE.Vector3(x, y, z) }
  }), [corpus, cutoff, earlier, frame, layout, timeMode, display, reference?.id])
  const selectedFeature = selected ? matchingFeature(selected) : undefined
  const priorCount = frame ? corpus.filter(post => stamp(post) < frame.origin).length : 0
  const pending = points.filter(point => point.pending).length
  const estimated = points.filter(point => point.estimated).length
  const matches = corpus.filter(post => `${post.author} ${post.handle || ''} ${post.text}`.toLowerCase().includes(query.toLowerCase()))
  const neighbors = selected ? corpus.filter(post => post.id !== selected.id && (post.parentId === selected.id || post.quotedPostId === selected.id || selected.parentId === post.id || selected.quotedPostId === post.id)) : []
  const visibleNeighbors = showAllConnections ? neighbors : neighbors.slice(0, 10)
  const capturedIds = new Set(corpus.map(post => post.id))
  const missingReferences = selected ? [selected.parentId, selected.quotedPostId].filter(id => id && !capturedIds.has(id)) : []
  const hoverPost = corpus.find(post => post.id === hovered?.id)
  const onSelectRef = useRef(setSelectedId)
  onSelectRef.current = setSelectedId

  useEffect(() => {
    if (!host.current || !frame || !reference) return
    try {
      const instance = createScene(host.current, frame, reference.id, display, id => onSelectRef.current(id), setHovered, cinematicRef.current, nodeBirths.current)
      api.current = instance; setFailure('')
      if (!cinematicRef.current) instance.showGuides()
      return () => { instance.dispose(); api.current = null }
    } catch {
      setFailure('3D rendering is unavailable in this browser. The post list and original source cards remain available.')
    }
  }, [frame, reference?.id])
  useEffect(() => { api.current?.configure(display) }, [display, frame])
  useEffect(() => { api.current?.update(points, activeId, links) }, [points, activeId, links, frame])
  useEffect(() => {
    if (!cinematic) api.current?.showGuides()
  }, [cinematic])
  useEffect(() => {
    if (layoutFitKeyRef.current === layoutFitKey) return
    layoutFitKeyRef.current = layoutFitKey
    api.current?.fit()
  }, [layoutFitKey])
  useEffect(() => { if (selected) onSelectPost?.(selected) }, [selected?.id, onSelectPost])
  useEffect(() => {
    if (!playing || !frame) return
    const started = performance.now()
    const from = timeX(frame, cursorRef.current ?? start, timeMode)
    const finish = timeX(frame, end, timeMode), begin = timeX(frame, start, timeMode)
    const timer = window.setInterval(() => {
      const next = Math.min(finish, from + (performance.now() - started) * (finish - begin) / 24000 * speed)
      setCursor(timeAtX(frame, next, timeMode))
      if (next >= finish) setPlaying(false)
    }, 40)
    return () => window.clearInterval(timer)
  }, [playing, start, end, speed, frame, timeMode])

  function choose(id: string) {
    setSelectedId(id)
    setShowAllConnections(false)
    const post = corpus.find(item => item.id === id)
    if (post && stamp(post) < start) setEarlier(true)
    if (post && stamp(post) > cutoff) { setCursor(stamp(post)); setPlaying(false) }
  }
  function replay() { setCursor(start); setPlaying(true); setSelectedId(reference?.id || ''); api.current?.reset() }

  if (compact) return <section className={`space-shell space-shell-compact${cinematic ? ' space-shell-cinematic' : ''}`} aria-label="Conversation Space">
    <div className="space-toolbar space-toolbar-compact">
      <div className="space-camera"><button onClick={() => api.current?.fit()} aria-label="Fit conversation"><Maximize2 size={15} /></button><button onClick={() => api.current?.reset()} aria-label="Reset camera"><RotateCcw size={15} /></button></div>
    </div>
    <div className="space-workspace space-workspace-compact">
      <div className="space-view"><div ref={host} className="space-canvas" />
        {!reference && <div className="space-canvas-note">Preparing the conversation.</div>}
        {failure && <div className="space-canvas-note" role="status">Posts remain available in the reading column.</div>}
        <div className="space-view-caption"><span className="space-status-dot" /> {points.length ? `${points.length} posts in view` : 'Waiting for the starting post'}</div>
        {hoverPost && hovered && <div className="space-hover" aria-hidden="true" style={{ left: `${hovered.x}%`, top: `${hovered.y}%` }}><strong>{authorName(hoverPost)}</strong><span>{hoverPost.text.slice(0, 150)}{hoverPost.text.length > 150 ? '…' : ''}</span></div>}
      </div>
    </div>
  </section>

  return <section className="space-shell" aria-label="Conversation Space">
    <div className="space-heading"><div><p className="space-eyebrow">CONVERSATION SPACE <span>{layout ? 'RECORDED' : liveSpaceMethod ? 'LIVE' : 'WAITING'}</span></p><h2>Time, meaning, and replies.</h2><p>{timeMode === 'flow' ? 'A continuous view of captured posts. Quiet gaps compressed.' : 'True elapsed time. Every post at its publication timestamp.'}</p></div><div className="space-count"><strong>{points.length}</strong><span>of {corpus.length} captured posts{estimated ? ` · ${estimated} lexical placements` : pending ? ` · ${pending} awaiting a position` : ''}</span></div></div>
    <div className="space-toolbar">
      <div className="space-segment" role="group" aria-label="Visible connections">{[['selected', 'Selected links'], ['all', 'All links'], ['none', 'No links']].map(([value, label]) => <button key={value} aria-pressed={links === value} onClick={() => setLinks(value)}>{label}</button>)}</div>
      <label className="space-earlier"><input type="checkbox" checked={earlier} onChange={event => { setEarlier(event.target.checked); setCursor(null); setPlaying(false) }} /> Include earlier posts {priorCount ? `(${priorCount})` : ''}</label>
      <div className="space-camera"><button onClick={() => api.current?.preset('side')}>Side</button><button onClick={() => api.current?.preset('end')}>End-on</button><button onClick={() => api.current?.fit()} aria-label="Fit conversation"><Maximize2 size={15} /></button><button onClick={() => api.current?.reset()} aria-label="Reset camera"><RotateCcw size={15} /></button></div>
    </div>
    <div className="space-layout-controls">
      <div className="space-segment" role="group" aria-label="Time spacing"><button aria-pressed={timeMode === 'flow'} onClick={() => setTimeMode('flow')}>Flow time</button><button aria-pressed={timeMode === 'elapsed'} onClick={() => setTimeMode('elapsed')}>Elapsed time</button></div>
      <label className="space-earlier"><input type="checkbox" checked={cone} onChange={event => setCone(event.target.checked)} /> Cone spread</label>
      <label className="space-width">Width <input aria-label="Semantic display width" type="range" min="0.6" max="2" step="0.1" value={spread} onChange={event => setSpread(Number(event.target.value))} /><output>{spread.toFixed(1)}×</output></label>
      <span>{cone ? 'Time-amplified display · cosine unchanged' : 'Uniform semantic distance scale'}</span>
    </div>
    <div className="space-workspace">
      <div className="space-view"><div ref={host} className="space-canvas" />
        {!reference && <div className="space-canvas-note">Waiting for a captured reference post.</div>}
        {failure && <div className="space-canvas-note" role="status">{failure}</div>}
        <div className="space-view-caption"><span className="space-status-dot" /> {cursor === null ? 'Captured scene · updates as posts arrive' : playing ? 'Replaying publication order' : 'Publication-time replay paused'}</div>
        {hoverPost && hovered && <div className="space-hover" aria-hidden="true" style={{ left: `${hovered.x}%`, top: `${hovered.y}%` }}><strong>{authorName(hoverPost)}</strong><small>{dateLabel(stamp(hoverPost))} UTC</small><span>{hoverPost.text.slice(0, 110)}{hoverPost.text.length > 110 ? '…' : ''}</span></div>}
        <div className="space-view-bottom"><span>Drag to orbit · scroll to zoom · click a post</span><span><i className="quote" />Quote <i className="reply" />Reply</span></div>
      </div>
      <aside className="space-inspector" aria-label="Selected space post">
        <label className="space-search"><Search size={15} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Find a post or author" aria-label="Find a space post" /></label>
        {query && <div className="space-matches">{matches.slice(0, 12).map(post => <button key={post.id} onClick={() => { choose(post.id); setQuery('') }}><strong>{post.author}</strong><span>{post.text.slice(0, 95)}</span></button>)}{!matches.length && <p>No captured matches.</p>}</div>}
        {selected ? <>
          <div className="space-post-heading"><span className="space-avatar">{selected.author.replace(/^@/, '').slice(0, 2).toUpperCase()}{selected.avatar && <img src={selected.avatar} alt="" onError={event => { event.currentTarget.style.display = 'none' }} />}</span><div><strong>{authorName(selected)}</strong>{selected.handle && authorName(selected).toLowerCase() !== `@${selected.handle}`.toLowerCase() && <span>@{selected.handle}</span>}</div>{selected.id === reference?.id && <small>REFERENCE</small>}</div>
          <time dateTime={selected.publishedAt}>{dateLabel(stamp(selected))} UTC</time>
          <p className="space-post-text">{selected.text}</p>
          {selected.textIsExcerpt && <p className="space-source-note">Captured excerpt; full text unavailable here.</p>}
          <div className="space-post-metrics">{selected.likes != null && <span><Heart size={14} />{selected.likes.toLocaleString()} captured likes</span>}{selected.url && <a href={selected.url} target="_blank" rel="noopener noreferrer">Open on X <ArrowUpRight size={13} /></a>}</div>
          <div className="space-readings"><div><span>FROM REFERENCE</span><strong>{frame ? elapsed(stamp(selected) - frame.origin) : '—'}</strong></div><div><span>{selected?.spaceMethod === 'lexical direction fallback' ? 'SEED MATCH' : 'SEED COSINE'}</span><strong>{selectedFeature ? selectedFeature.cosine.toFixed(3) : 'Awaiting score'}</strong></div></div>
          {selectedFeature?.estimated && <p className="space-source-note">Saved projection unavailable for this later-captured post. Its angle is a stable lexical estimate; a live embedding will replace it when available.</p>}
          {selectedFeature?.inputTruncated && <p className="space-source-note">Embedding uses a token-limited excerpt of the captured text.</p>}
          {!points.some(point => point.post.id === selected.id) && <p className="space-source-note">Selected post is outside the visible time window.</p>}
          <div className="space-post-actions"><button onClick={() => api.current?.focus(selected.id)}><Focus size={14} />Focus camera</button><button onClick={() => onOpenPost(selected)}>Source context <ArrowUpRight size={14} /></button></div>
          <div className="space-connections"><h3>Recorded connections <span>{neighbors.length}</span></h3>{visibleNeighbors.map(post => <button key={post.id} onClick={() => choose(post.id)}><span>{authorName(post)}</span><small>{post.quotedPostId === selected.id ? 'quotes this' : post.parentId === selected.id ? 'replies to this' : selected.quotedPostId === post.id ? 'quoted post' : 'parent post'} <ArrowUpRight size={12} /></small></button>)}{neighbors.length > 10 && <button type="button" className="space-connections-more" onClick={() => setShowAllConnections(value => !value)}>{showAllConnections ? 'Show fewer connections' : `Show all ${neighbors.length} connections`}</button>}{!neighbors.length && !missingReferences.length && <p>No captured quote or reply links.</p>}{missingReferences.map(id => <a key={id} href={`https://x.com/i/status/${id}`} target="_blank" rel="noopener noreferrer">Referenced post not captured <ArrowUpRight size={12} /></a>)}</div>
        </> : <p className="space-source-note">Select a post to read its original text.</p>}
      </aside>
    </div>
    <div className="space-playback"><button className="space-play" disabled={!corpus.length} onClick={() => playing ? setPlaying(false) : cursor !== null && cursor < end ? setPlaying(true) : replay()} aria-label={playing ? 'Pause time replay' : 'Play time replay'}>{playing ? <Pause size={17} /> : <Play size={17} />}</button><div className="space-scrubber"><div><span>{frame ? dateLabel(start) : '—'} UTC</span><strong>{cursor === null ? 'All received posts' : `${dateLabel(cutoff)} UTC`}</strong><span>{frame ? dateLabel(end) : '—'} UTC</span></div><input aria-label="Publication time" aria-valuetext={frame ? `${dateLabel(cutoff)} UTC` : 'Waiting for captured posts'} type="range" min={frame ? timeX(frame, start, timeMode) : 0} max={frame ? timeX(frame, end, timeMode) : 1} step="any" value={frame ? timeX(frame, cutoff, timeMode) : 1} onChange={event => { if (frame) setCursor(timeAtX(frame, Number(event.target.value), timeMode)); setPlaying(false) }} /></div><select aria-label="Replay speed" value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value={.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option></select><button className="space-show-all" onClick={() => { setCursor(null); setPlaying(false) }}>Show all</button></div>
    <div className="space-foot"><span title={layout ? artifact.model : liveSpaceMethod}>{layout ? `${artifact.model.split('@')[0]} · frozen semantic projection` : liveSpaceMethod ? `Live projection · ${liveSpaceMethod}` : 'Waiting for live ranking to position captured posts'}</span><span>{cone ? 'Cone width amplifies semantic departure with time; it is a visual treatment, not a comparable distance scale.' : 'Radius measures departure from the seed’s captured text.'} {selectedFeature?.estimated || selected?.spaceMethod === 'lexical direction fallback' ? 'Estimated placements use retrieval similarity for radius; shared terms determine a stable angle.' : 'Cosine scores are unchanged. Angle is a lossy projection.'}</span><span>{timeMode === 'flow' ? 'Flow spacing compresses captured gaps and expands dense bursts; horizontal distance is not elapsed time.' : 'Horizontal distance represents elapsed publication time.'} No timestamps are shifted and no posts are added. Replay follows publication order.</span></div>
    <details className="space-accessible-list"><summary>Browse captured posts without the 3D view</summary><div>{corpus.map(post => <button key={post.id} onClick={() => choose(post.id)}><strong>{post.author}</strong><span>{post.text.slice(0, 140)}</span></button>)}</div></details>
  </section>
}
