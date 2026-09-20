import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import './search-intro.css'

export type SearchIntroPhase = 'idle' | 'searching' | 'resolving'
export type SearchIntroProps = { phase: SearchIntroPhase; className?: string }
type Card = { author: string; handle: string; text: string; accent: string; likes: string }

const CARDS: Card[] = [
  { author: 'Dario Amodei', handle: '@DarioAmodei', text: 'We Must Pace the Frontier. I’ve written a new essay on why the AI industry should slow down.', accent: '#94cfee', likes: '87K' },
  { author: 'Sam Altman', handle: '@sama', text: 'I agree with Dario that we need to pace the frontier.', accent: '#78c8e2', likes: '67K' },
  { author: 'Elon Musk', handle: '@elonmusk', text: 'Dario is right', accent: '#d7e7f0', likes: '58K' },
  { author: 'Demis Hassabis', handle: '@demishassabis', text: "Dario's essay points towards the right path forward.", accent: '#b9a9f3', likes: '9.1K' },
  { author: 'Sen. Bernie Sanders', handle: '@SenSanders', text: 'When you are racing towards a cliff, you don’t just ease up on the gas pedal.', accent: '#a8d8b9', likes: '9.8K' },
  { author: 'manic_pixie_agi', handle: '@manic_pixie_agi', text: 'good morning, who up pacing they frontier', accent: '#f1b4ce', likes: '11' },
  { author: 'Emad', handle: '@EMostaque', text: 'Thoughts on the pacing the frontier proposal. Well intentioned, but with logical flaws.', accent: '#e8c58d', likes: '433' },
  { author: 'The Little Platoon', handle: '@PlatoonPod', text: 'A great many frontier technologies have an equivalent historical story.', accent: '#bfbcf4', likes: '582' },
  { author: 'Aakash Gupta', handle: '@aakashg0', text: 'A single essay got the CEOs of both leading labs to accept outside inspectors.', accent: '#8dd9d2', likes: '53' },
  { author: 'The Trend Sage', handle: '@JonkooTrades', text: '“Pacing the frontier” is not the same as pausing AI.', accent: '#9dbce9', likes: '22' },
  { author: 'Simone Scavo', handle: '@Simne1core', text: 'For the first time one of the builders is saying this out loud.', accent: '#e1a7d7', likes: '143' },
  { author: 'Avi Loeb', handle: '@ProfAviLoeb', text: 'Defining a new research frontier on artificial intelligence.', accent: '#c3daa0', likes: '76' },
  { author: 'Mimi Yamazaki', handle: '@positivenumber1', text: 'The conversation has become impossible to ignore.', accent: '#dcad9e', likes: '31' },
  { author: 'Tae Kim', handle: '@firstadopter', text: 'WE MUST PACE THE FRONTIER!', accent: '#a2cfed', likes: '18' },
  { author: 'Sabrina', handle: '@Sabrina7772', text: 'The people raising these concerns include people actually building frontier AI.', accent: '#eab5c1', likes: '52' },
  { author: 'Stephen Malina', handle: '@an1lam', text: 'I wanted to share my thoughts on this. All my personal opinions.', accent: '#94d8c0', likes: '28' },
  { author: 'Zak Mndebele', handle: '@ZakMndebele', text: 'One of the better AI safety proposals of the past few days.', accent: '#c9b1f2', likes: '45' },
  { author: 'La Défense YIMBY', handle: '@BarneyFlames', text: 'Independent evaluators, advised and funded by Anthropic.', accent: '#d8d499', likes: '75' },
  { author: 'The research feed', handle: '@researchfeed', text: 'What the timeline does with a claim is its own kind of story.', accent: '#a6bee7', likes: '143' },
  { author: 'A reply', handle: '@a_reply', text: 'The joke arrived before the explanation.', accent: '#e1adca', likes: '29' },
  { author: 'A source', handle: '@source', text: 'A source is a beginning, not a destination.', accent: '#a0dfce', likes: '61' },
  { author: 'A question', handle: '@question', text: 'Watch where the context bends.', accent: '#e0c39d', likes: '19' },
  { author: 'The timeline', handle: '@timeline', text: 'One sentence, many directions.', accent: '#b4b8ed', likes: '32' },
  { author: 'The thread', handle: '@thread', text: 'Follow the thread, then follow what it became.', accent: '#94d1ed', likes: '84' },
]

type CardObject = { mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>; base: THREE.Vector3; rotation: THREE.Euler; phase: number; index: number }
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))
function rounded(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) { context.beginPath(); context.roundRect(x, y, width, height, radius); context.fill() }
function wrap(context: CanvasRenderingContext2D, text: string, width: number) { const words = text.split(' '), rows: string[] = []; let row = ''; for (const word of words) { const next = row ? `${row} ${word}` : word; if (context.measureText(next).width > width && row) { rows.push(row); row = word } else row = next } if (row) rows.push(row); return rows }
function textureFor(card: Card) {
  const canvas = document.createElement('canvas'); canvas.width = 720; canvas.height = 470
  const context = canvas.getContext('2d')!
  context.fillStyle = '#0b1219'; rounded(context, 4, 4, 712, 462, 28)
  context.strokeStyle = '#314654'; context.lineWidth = 2; context.beginPath(); context.roundRect(4, 4, 712, 462, 28); context.stroke()
  const sheen = context.createLinearGradient(0, 0, 720, 470); sheen.addColorStop(0, `${card.accent}28`); sheen.addColorStop(.45, '#00000000'); sheen.addColorStop(1, '#00000010'); context.fillStyle = sheen; rounded(context, 4, 4, 712, 462, 28)
  context.fillStyle = card.accent; context.beginPath(); context.arc(70, 76, 29, 0, Math.PI * 2); context.fill()
  context.fillStyle = '#0c151d'; context.font = '700 27px system-ui'; context.textAlign = 'center'; context.textBaseline = 'middle'; context.fillText(card.author[0].toUpperCase(), 70, 79)
  context.textAlign = 'left'; context.fillStyle = '#f3f7fa'; context.font = '650 27px system-ui'; context.fillText(card.author, 118, 68)
  context.fillStyle = '#91a3b1'; context.font = '20px system-ui'; context.fillText(card.handle, 118, 96)
  context.fillStyle = '#e7edf2'; context.font = '500 33px system-ui'; wrap(context, card.text, 610).slice(0, 4).forEach((line, index) => context.fillText(line, 48, 175 + index * 44))
  context.fillStyle = '#6f8291'; context.font = '20px system-ui'; context.fillText('◌   ◌   ♡   ↗', 48, 410); context.textAlign = 'right'; context.fillText(card.likes, 667, 410)
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace; texture.minFilter = THREE.LinearFilter; return texture
}

export default function SearchIntro({ phase, className = '' }: SearchIntroProps) {
  const hostRef = useRef<HTMLDivElement>(null), phaseRef = useRef(phase), phaseSince = useRef(performance.now())
  useEffect(() => { phaseRef.current = phase; phaseSince.current = performance.now() }, [phase])
  useEffect(() => {
    const host = hostRef.current; if (!host) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false }); renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75)); renderer.setClearColor('#000000'); renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.domElement.className = 'search-intro-canvas'; host.appendChild(renderer.domElement)
    const scene = new THREE.Scene(); scene.fog = new THREE.FogExp2('#000000', .018); const camera = new THREE.PerspectiveCamera(52, 1, .1, 300); const cards = new THREE.Group(); scene.add(cards)
    const geometry = new THREE.PlaneGeometry(5.7, 3.72), objects: CardObject[] = []
    CARDS.forEach((card, index) => {
      const lane = (index % 6) - 2.5, row = Math.floor(index / 6), depth = -15 - row * 17 - (index % 3) * 3
      const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ map: textureFor(card), transparent: true, opacity: .98, side: THREE.DoubleSide, depthWrite: false }))
      const base = new THREE.Vector3(lane * 4.55 + Math.sin(index * 7.2) * 1.3, ((index * 3) % 5 - 2) * 2.25 + row * .7, depth), rotation = new THREE.Euler(Math.sin(index * 1.7) * .13, Math.cos(index * 2.3) * .22, Math.sin(index * 1.31) * .09)
      mesh.position.copy(base); mesh.rotation.copy(rotation); mesh.scale.setScalar(.78 + (index % 4) * .07); cards.add(mesh); objects.push({ mesh, base, rotation, phase: index * .71, index })
    })
    const streakGeometry = new THREE.BufferGeometry(), streaks = new Float32Array(180 * 2 * 3)
    for (let index = 0; index < 180; index++) { const offset = index * 6, x = ((index * 47) % 91 - 45) * .8, y = ((index * 31) % 61 - 30) * .45, z = -8 - (index % 19) * 7; streaks.set([x, y, z, x, y, z - 13], offset) }
    streakGeometry.setAttribute('position', new THREE.BufferAttribute(streaks, 3)); const streakMaterial = new THREE.LineBasicMaterial({ color: '#9bd9ff', transparent: true, opacity: 0, depthWrite: false }), streakLines = new THREE.LineSegments(streakGeometry, streakMaterial); scene.add(streakLines)
    const resize = () => { const { width, height } = host.getBoundingClientRect(); renderer.setSize(Math.max(1, width), Math.max(1, height), false); camera.aspect = Math.max(1, width) / Math.max(1, height); camera.updateProjectionMatrix() }; const observer = new ResizeObserver(resize); observer.observe(host); resize()
    let request = 0, disposed = false
    const render = (now: number) => {
      if (disposed) return
      const age = now - phaseSince.current, resolving = phaseRef.current === 'resolving', travel = resolving ? 1 : clamp(age / 5400, 0, 1)
      camera.position.set(Math.sin(now * .00017) * .38, Math.cos(now * .00013) * .2, 5 - travel * 41 - (resolving ? clamp(age / 950, 0, 1) * 32 : 0)); camera.lookAt(0, 0, camera.position.z - 31)
      objects.forEach(({ mesh, base, rotation, phase: offset, index }) => {
        const natural = clamp((age - (1750 + index * 150)) / 2100, 0, 1), rush = resolving ? clamp(age / 520, 0, 1) : 0, dissolve = Math.max(natural, rush), drift = reduced ? 0 : Math.sin(now * .00055 + offset) * .35
        mesh.position.set(base.x + drift, base.y + Math.cos(now * .00041 + offset) * .22, base.z + Math.sin(now * .00033 + offset) * .8); mesh.rotation.set(rotation.x + Math.sin(now * .0004 + offset) * .04, rotation.y + Math.cos(now * .00031 + offset) * .05, rotation.z + Math.sin(now * .00045 + offset) * .045); mesh.scale.setScalar((.78 + (index % 4) * .07) * (1 - dissolve * .72)); mesh.material.opacity = (1 - dissolve) * .98; mesh.visible = dissolve < .997
      })
      const rush = resolving ? clamp(age / 950, 0, 1) : 0; streakMaterial.opacity = rush < .92 ? Math.sin(rush * Math.PI) * .82 : 0; streakLines.position.z = camera.position.z - 2
      renderer.render(scene, camera); request = requestAnimationFrame(render)
    }
    request = requestAnimationFrame(render)
    return () => { disposed = true; cancelAnimationFrame(request); observer.disconnect(); objects.forEach(item => { item.mesh.material.map?.dispose(); item.mesh.material.dispose() }); geometry.dispose(); streakGeometry.dispose(); streakMaterial.dispose(); renderer.dispose(); renderer.domElement.remove() }
  }, [])
  return <section className={`search-intro ${className}`.trim()} aria-label="Tracing the Dario conversation"><div className="search-intro-stage" ref={hostRef} /></section>
}
