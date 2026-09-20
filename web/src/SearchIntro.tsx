import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import './search-intro.css'

export type SearchIntroPhase = 'idle' | 'searching' | 'resolving'
export type SearchIntroProps = { phase: SearchIntroPhase; className?: string }
type Card = { author: string; handle: string; text: string; accent: string; year: string }

const CARDS: Card[] = [
  { author: 'Jack Dorsey', handle: '@jack', text: 'just setting up my twttr', accent: '#94cfee', year: '2006' },
  { author: 'Kanye West', handle: '@kanyewest', text: 'I hate when I’m on a flight and I wake up with a water bottle next to me like oh great now I gotta be responsible for this water bottle.', accent: '#e8c58d', year: '2010' },
  { author: 'Sohaib Athar', handle: '@ReallyVirtual', text: 'Helicopter hovering above Abbottabad at 1AM (is a rare event).', accent: '#a8d8b9', year: '2011' },
  { author: 'Keith Urbahn', handle: '@keithurbahn', text: 'So I’m told by a reputable person they have killed Osama Bin Laden. Hot damn.', accent: '#9dbce9', year: '2011' },
  { author: 'Horse ebooks', handle: '@Horse_ebooks', text: 'Everything happens so much', accent: '#f1b4ce', year: '2012' },
  { author: 'wint', handle: '@dril', text: 'IF THE ZOO BANS ME FOR HOLLERING AT THE ANIMALS I WILL FACE GOD AND WALK BACKWARDS INTO HELL', accent: '#bfbcf4', year: '2012' },
  { author: 'Curiosity Rover', handle: '@MarsCuriosity', text: 'I’m safely on the surface of Mars. GALE CRATER I AM IN YOU!!! #MSL', accent: '#dcad9e', year: '2012' },
  { author: 'Pope Benedict XVI', handle: '@Pontifex', text: 'Dear friends, I am pleased to get in touch with you through Twitter. Thank you for your generous response. I bless all of you from my heart.', accent: '#d8d499', year: '2012' },
  { author: 'wint', handle: '@dril', text: 'Food $200 Data $150 Rent $800 Candles $3,600 Utility $150 someone who is good at the economy please help me budget this. my family is dying', accent: '#c9b1f2', year: '2013' },
  { author: 'Stephen King', handle: '@StephenKing', text: 'My first tweet. No longer a virgin. Be gentle!', accent: '#e1a7d7', year: '2013' },
  { author: 'CIA', handle: '@CIA', text: 'We can neither confirm nor deny that this is our first tweet.', accent: '#78c8e2', year: '2014' },
  { author: 'Leonard Nimoy', handle: '@TheRealNimoy', text: 'A life is like a garden. Perfect moments can be had, but not preserved, except in memory. LLAP', accent: '#b9a9f3', year: '2015' },
  { author: 'Edward Snowden', handle: '@Snowden', text: 'Can you hear me now?', accent: '#a0dfce', year: '2015' },
  { author: 'Hillary Clinton', handle: '@HillaryClinton', text: 'Delete your account.', accent: '#a2cfed', year: '2016' },
  { author: 'Netflix', handle: '@netflix', text: 'Love is sharing a password.', accent: '#eab5c1', year: '2017' },
  { author: 'Donald J. Trump', handle: '@realDonaldTrump', text: 'Despite the constant negative press covfefe', accent: '#d7e7f0', year: '2017' },
  { author: 'Malala Yousafzai', handle: '@Malala', text: 'Hi, Twitter.', accent: '#94d8c0', year: '2017' },
  { author: 'Elon Musk', handle: '@elonmusk', text: 'Am considering taking Tesla private at $420. Funding secured.', accent: '#c3daa0', year: '2018' },
  { author: 'Greta Thunberg', handle: '@GretaThunberg', text: 'So ridiculous. Donald must work on his Anger Management problem, then go to a good old fashioned movie with a friend! Chill Donald, Chill!', accent: '#8dd9d2', year: '2020' },
  { author: 'Joe Biden', handle: '@JoeBiden', text: 'It’s a new day in America.', accent: '#94d1ed', year: '2021' },
  { author: 'Twitter', handle: '@Twitter', text: 'hello literally everyone', accent: '#a6bee7', year: '2021' },
  { author: 'Elon Musk', handle: '@elonmusk', text: 'the bird is freed', accent: '#e0c39d', year: '2022' },
]

type CardObject = { mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>; base: THREE.Vector3; rotation: THREE.Euler; phase: number; index: number }
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))
function rounded(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) { context.beginPath(); context.roundRect(x, y, width, height, radius); context.fill() }
function wrap(context: CanvasRenderingContext2D, text: string, width: number) { const words = text.split(' '), rows: string[] = []; let row = ''; for (const word of words) { const next = row ? `${row} ${word}` : word; if (context.measureText(next).width > width && row) { rows.push(row); row = word } else row = next } if (row) rows.push(row); return rows }
function drawText(context: CanvasRenderingContext2D, text: string) {
  let size = 33, rows: string[] = []
  do { context.font = `500 ${size}px system-ui`; rows = wrap(context, text, 610); size-- } while (rows.length > 5 && size >= 25)
  const lineHeight = Math.round((size + 1) * 1.3)
  rows.slice(0, 5).forEach((line, index) => context.fillText(line, 48, 165 + index * lineHeight))
}
function textureFor(card: Card) {
  const canvas = document.createElement('canvas'); canvas.width = 720; canvas.height = 470
  const context = canvas.getContext('2d')!
  context.fillStyle = '#000000'; rounded(context, 4, 4, 712, 462, 28)
  context.strokeStyle = '#2f3336'; context.lineWidth = 2; context.beginPath(); context.roundRect(4, 4, 712, 462, 28); context.stroke()
  context.fillStyle = card.accent; context.beginPath(); context.arc(70, 76, 29, 0, Math.PI * 2); context.fill()
  context.fillStyle = '#0c151d'; context.font = '700 27px system-ui'; context.textAlign = 'center'; context.textBaseline = 'middle'; context.fillText(card.author[0].toUpperCase(), 70, 79)
  context.textAlign = 'left'; context.fillStyle = '#f3f7fa'; context.font = '650 27px system-ui'; context.fillText(card.author, 118, 68)
  context.fillStyle = '#91a3b1'; context.font = '20px system-ui'; context.fillText(card.handle, 118, 96)
  context.fillStyle = '#e7edf2'; drawText(context, card.text)
  context.fillStyle = '#6f8291'; context.font = '20px system-ui'; context.fillText('◌   ◌   ♡   ↗', 48, 410); context.textAlign = 'right'; context.fillText(card.year, 667, 410)
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace; texture.minFilter = THREE.LinearFilter; return texture
}

export default function SearchIntro({ phase, className = '' }: SearchIntroProps) {
  const hostRef = useRef<HTMLDivElement>(null), phaseRef = useRef(phase), journeySince = useRef(performance.now()), phaseSince = useRef(performance.now())
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
      const journeyAge = now - journeySince.current, phaseAge = now - phaseSince.current, resolving = phaseRef.current === 'resolving', travel = clamp(journeyAge / 5400, 0, 1)
      camera.position.set(reduced ? 0 : Math.sin(now * .00017) * .38, reduced ? 0 : Math.cos(now * .00013) * .2, 5 - travel * 41 - (resolving ? clamp(phaseAge / 950, 0, 1) * 32 : 0)); camera.lookAt(0, 0, camera.position.z - 31)
      objects.forEach(({ mesh, base, rotation, phase: offset, index }) => {
        const natural = clamp((journeyAge - (1750 + index * 150)) / 2100, 0, 1), rush = resolving ? clamp(phaseAge / 520, 0, 1) : 0, dissolve = Math.max(natural, rush), drift = reduced ? 0 : Math.sin(now * .00055 + offset) * .35
        mesh.position.set(base.x + drift, base.y + (reduced ? 0 : Math.cos(now * .00041 + offset) * .22), base.z + (reduced ? 0 : Math.sin(now * .00033 + offset) * .8)); mesh.rotation.set(rotation.x + (reduced ? 0 : Math.sin(now * .0004 + offset) * .04), rotation.y + (reduced ? 0 : Math.cos(now * .00031 + offset) * .05), rotation.z + (reduced ? 0 : Math.sin(now * .00045 + offset) * .045)); mesh.scale.setScalar((.78 + (index % 4) * .07) * (1 - dissolve * .72)); mesh.material.opacity = (1 - dissolve) * .98; mesh.visible = dissolve < .997
      })
      const rush = resolving ? clamp(phaseAge / 950, 0, 1) : 0; streakMaterial.opacity = reduced ? 0 : rush < .92 ? Math.sin(rush * Math.PI) * .82 : 0; streakLines.position.z = camera.position.z - 2
      renderer.render(scene, camera); request = requestAnimationFrame(render)
    }
    request = requestAnimationFrame(render)
    return () => { disposed = true; cancelAnimationFrame(request); observer.disconnect(); objects.forEach(item => { item.mesh.material.map?.dispose(); item.mesh.material.dispose() }); geometry.dispose(); streakGeometry.dispose(); streakMaterial.dispose(); scene.clear(); renderer.renderLists.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove() }
  }, [])
  return <section className={`search-intro ${className}`.trim()} aria-label="Tracing the public conversation"><div className="search-intro-stage" ref={hostRef} /></section>
}
