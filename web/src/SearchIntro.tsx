import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import './search-intro.css'

export type SearchIntroPhase = 'idle' | 'searching' | 'resolving'

export type SearchIntroProps = {
  /** The server work has deliberately no bearing on this decorative scene. */
  phase: SearchIntroPhase
  onSkip?: () => void
  className?: string
}

type Card = {
  author: string
  handle: string
  text: string
  tint: string
}

// These are short, local display-only excerpts. They are never mixed into a
// search result or passed to the API, so the loading scene is repeatable.
const CARDS: Card[] = [
  { author: 'Ada', handle: '@ada', text: 'A good question changes the shape of the room.', tint: '#93d8ff' },
  { author: 'Mara', handle: '@marawrites', text: 'The first version of a story is usually a signal, not an ending.', tint: '#d9b6ff' },
  { author: 'River', handle: '@river', text: 'Ideas travel faster when they can be retold.', tint: '#8ee3ca' },
  { author: 'Noah', handle: '@noah', text: 'Everyone saw the announcement. Everyone heard something different.', tint: '#ffcc91' },
  { author: 'June', handle: '@june', text: 'The joke arrived before the explanation.', tint: '#ff9eb8' },
  { author: 'Sol', handle: '@sol', text: 'A source is a beginning, not a destination.', tint: '#9eb9ff' },
  { author: 'Mina', handle: '@mina', text: 'Watch where the context bends.', tint: '#b2e8a6' },
  { author: 'Eli', handle: '@eli', text: 'A reply can carry a whole second story.', tint: '#e5b9a8' },
  { author: 'Iris', handle: '@iris', text: 'The timeline is only one view of the conversation.', tint: '#b2d1ff' },
  { author: 'Kai', handle: '@kai', text: 'The interesting part is what happens next.', tint: '#e0c4ff' },
  { author: 'Nia', handle: '@nia', text: 'One sentence, many directions.', tint: '#97e0dc' },
  { author: 'Theo', handle: '@theo', text: 'Follow the thread, then follow what it became.', tint: '#ffd49d' },
]

type CardObject = {
  mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>
  position: THREE.Vector3
  rotation: THREE.Euler
  drift: number
  phase: number
  index: number
}

function roundedRect(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  context.beginPath()
  context.roundRect(x, y, width, height, radius)
  context.fill()
}

function lines(context: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.split(' ')
  const result: string[] = []
  let current = ''
  for (const word of words) {
    const next = current ? `${current} ${word}` : word
    if (context.measureText(next).width > maxWidth && current) {
      result.push(current)
      current = word
    } else current = next
  }
  if (current) result.push(current)
  return result
}

function cardTexture(card: Card) {
  const canvas = document.createElement('canvas')
  canvas.width = 620
  canvas.height = 400
  const context = canvas.getContext('2d')!
  context.fillStyle = '#101a25'
  roundedRect(context, 3, 3, 614, 394, 28)
  context.strokeStyle = '#385067'
  context.lineWidth = 2
  context.beginPath()
  context.roundRect(3, 3, 614, 394, 28)
  context.stroke()
  const glow = context.createRadialGradient(118, 84, 0, 118, 84, 210)
  glow.addColorStop(0, `${card.tint}28`)
  glow.addColorStop(1, '#00000000')
  context.fillStyle = glow
  roundedRect(context, 3, 3, 614, 394, 28)
  context.fillStyle = card.tint
  context.beginPath()
  context.arc(70, 72, 27, 0, Math.PI * 2)
  context.fill()
  context.fillStyle = '#0d1720'
  context.font = '700 25px Inter, system-ui, sans-serif'
  context.textAlign = 'center'
  context.textBaseline = 'middle'
  context.fillText(card.author.slice(0, 1).toUpperCase(), 70, 74)
  context.textAlign = 'left'
  context.fillStyle = '#eef7ff'
  context.font = '600 24px Inter, system-ui, sans-serif'
  context.fillText(card.author, 113, 65)
  context.fillStyle = '#8fa7bb'
  context.font = '19px Inter, system-ui, sans-serif'
  context.fillText(card.handle, 113, 91)
  context.fillStyle = '#e5edf4'
  context.font = '500 31px Inter, system-ui, sans-serif'
  const textLines = lines(context, card.text, 520).slice(0, 4)
  textLines.forEach((line, index) => context.fillText(line, 48, 165 + index * 42))
  context.fillStyle = '#7790a5'
  context.font = '18px Inter, system-ui, sans-serif'
  context.fillText('captured thought', 48, 347)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.minFilter = THREE.LinearFilter
  return texture
}

function clamp(value: number, low: number, high: number) { return Math.min(high, Math.max(low, value)) }

/**
 * A self-contained, intentionally non-interactive loading scene. Parent code
 * only supplies phase changes and may replace it with the real graph at any
 * time. The visual has no data dependency or network requests.
 */
export default function SearchIntro({ phase, onSkip, className = '' }: SearchIntroProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const phaseRef = useRef<SearchIntroPhase>(phase)
  const phaseSinceRef = useRef(performance.now())
  const reducedRef = useRef(false)

  useEffect(() => {
    phaseRef.current = phase
    phaseSinceRef.current = performance.now()
  }, [phase])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const reducedMedia = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedRef.current = reducedMedia.matches
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.domElement.className = 'search-intro-canvas'
    renderer.domElement.setAttribute('aria-hidden', 'true')
    host.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    scene.fog = new THREE.FogExp2('#071019', .027)
    const camera = new THREE.PerspectiveCamera(42, 1, .1, 300)
    camera.position.set(0, 1.5, 22)
    const cardsGroup = new THREE.Group()
    scene.add(cardsGroup)
    const cardObjects: CardObject[] = []
    const cardGeometry = new THREE.PlaneGeometry(5.2, 3.35)
    CARDS.forEach((card, index) => {
      const angle = index * 2.399963229728653
      const ring = 5.4 + (index % 4) * 3.15
      const depth = -8 - (index % 5) * 4.4
      const material = new THREE.MeshBasicMaterial({ map: cardTexture(card), transparent: true, opacity: .94, side: THREE.DoubleSide, depthWrite: false })
      const mesh = new THREE.Mesh(cardGeometry, material)
      const position = new THREE.Vector3(Math.cos(angle) * ring * 1.35, Math.sin(angle * 1.71) * ring * .6, depth)
      const rotation = new THREE.Euler(Math.sin(angle) * .16, -Math.cos(angle) * .21, Math.sin(angle * 2) * .13)
      mesh.position.copy(position)
      mesh.rotation.copy(rotation)
      mesh.scale.setScalar(.72 + (index % 3) * .11)
      cardsGroup.add(mesh)
      cardObjects.push({ mesh, position, rotation, drift: .13 + (index % 5) * .027, phase: angle, index })
    })

    const anchor = new THREE.Group()
    anchor.visible = false
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(.68, 3), new THREE.MeshBasicMaterial({ color: '#dff6ff', transparent: true, opacity: 0 }))
    const halo = new THREE.Mesh(new THREE.TorusGeometry(1.12, .025, 12, 64), new THREE.MeshBasicMaterial({ color: '#87d9ff', transparent: true, opacity: 0 }))
    const halo2 = new THREE.Mesh(new THREE.TorusGeometry(1.58, .012, 8, 64), new THREE.MeshBasicMaterial({ color: '#c1a8ff', transparent: true, opacity: 0 }))
    halo.rotation.x = Math.PI / 2.45
    halo2.rotation.x = Math.PI / 1.82
    anchor.add(core, halo, halo2)
    scene.add(anchor)
    const starsGeometry = new THREE.BufferGeometry()
    const starPositions = new Float32Array(360 * 3)
    for (let index = 0; index < 360; index++) {
      const n = index * 3, theta = index * 2.399963229728653, radius = 12 + (index % 17) * 1.45
      starPositions[n] = Math.cos(theta) * radius
      starPositions[n + 1] = Math.sin(theta * 1.7) * radius * .58
      starPositions[n + 2] = -26 - (index % 13) * 4
    }
    starsGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3))
    const stars = new THREE.Points(starsGeometry, new THREE.PointsMaterial({ color: '#8ebed5', size: .038, transparent: true, opacity: .48, depthWrite: false }))
    scene.add(stars)

    const resize = () => {
      const { width, height } = host.getBoundingClientRect()
      renderer.setSize(Math.max(1, width), Math.max(1, height), false)
      camera.aspect = Math.max(1, width) / Math.max(1, height)
      camera.updateProjectionMatrix()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(host)
    resize()
    let frame = 0
    let disposed = false
    const render = (now: number) => {
      if (disposed) return
      const reduced = reducedRef.current
      const age = now - phaseSinceRef.current
      const activePhase = phaseRef.current
      const resolving = activePhase === 'resolving'
      const searching = activePhase === 'searching'
      const anchorProgress = resolving ? clamp((age - 700) / 700, 0, 1) : 0
      anchor.visible = anchorProgress > 0
      ;(core.material as THREE.MeshBasicMaterial).opacity = anchorProgress
      ;(halo.material as THREE.MeshBasicMaterial).opacity = anchorProgress * .82
      ;(halo2.material as THREE.MeshBasicMaterial).opacity = anchorProgress * .65
      anchor.scale.setScalar(.5 + anchorProgress * .5)
      if (!reduced) {
        anchor.rotation.y = now * .00032
        halo.rotation.z = now * .00028
        halo2.rotation.z = -now * .00021
        stars.rotation.y = now * .000009
      }
      cardObjects.forEach(({ mesh, position, rotation, drift, phase: offset, index }) => {
        const disappear = resolving ? clamp((age - index * 105) / 620, 0, 1) : 0
        const pulse = searching ? .92 + Math.sin(now * .0022 + offset) * .055 : 1
        const movement = reduced ? 0 : Math.sin(now * drift * .001 + offset) * .34
        mesh.position.set(position.x + Math.cos(offset) * movement, position.y + Math.sin(offset * 1.3) * movement, position.z + Math.sin(now * .0007 + offset) * .3)
        mesh.rotation.set(rotation.x + movement * .025, rotation.y, rotation.z + Math.sin(now * .0008 + offset) * .025)
        const scale = (1 - disappear * .8) * pulse
        mesh.scale.setScalar(scale * (.72 + (index % 3) * .11))
        mesh.material.opacity = (1 - disappear) * .94
        mesh.visible = disappear < .999
      })
      if (!reduced) camera.position.x = Math.sin(now * .00011) * .7
      camera.lookAt(0, 0, -9)
      renderer.render(scene, camera)
      if (!reduced || activePhase !== 'idle') frame = requestAnimationFrame(render)
    }
    frame = requestAnimationFrame(render)
    const motionChange = () => {
      reducedRef.current = reducedMedia.matches
      if (reducedRef.current) renderer.render(scene, camera)
      else if (!frame) frame = requestAnimationFrame(render)
    }
    reducedMedia.addEventListener('change', motionChange)
    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      observer.disconnect()
      reducedMedia.removeEventListener('change', motionChange)
      cardObjects.forEach(({ mesh }) => { mesh.material.map?.dispose(); mesh.material.dispose() })
      cardGeometry.dispose()
      ;(core.geometry as THREE.BufferGeometry).dispose(); (core.material as THREE.Material).dispose()
      ;(halo.geometry as THREE.BufferGeometry).dispose(); (halo.material as THREE.Material).dispose()
      ;(halo2.geometry as THREE.BufferGeometry).dispose(); (halo2.material as THREE.Material).dispose()
      starsGeometry.dispose(); (stars.material as THREE.Material).dispose()
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [])

  const status = phase === 'idle' ? 'Ready when you are' : phase === 'searching' ? 'Tracing the conversation' : 'Finding the first signal'
  return <section className={`search-intro ${className}`.trim()} aria-label="Search in progress">
    <div className="search-intro-stage" ref={hostRef} />
    <div className="search-intro-copy" aria-live="polite"><p>{status}</p></div>
    {onSkip && phase !== 'idle' && <button className="search-intro-skip" type="button" onClick={onSkip}>Skip intro</button>}
  </section>
}
