import { useEffect, useMemo, useRef } from 'react'
import type { CSSProperties } from 'react'
import './search-intro.css'

export type SearchIntroPhase = 'idle' | 'searching' | 'resolving'
export type SearchIntroPost = { author?: string; handle?: string; text: string; publishedAt?: string }
export type SearchIntroProps = { phase: SearchIntroPhase; className?: string; posts?: SearchIntroPost[] }

type Card = { author: string; handle: string; text: string; accent: string; year: string }
type PlacedCard = Card & {
  key: string
  x: number
  y: number
  z: number
  rx: number
  ry: number
  width: number
}

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

const FIELD_SIZE = 220
const GOLDEN = 2.399963229728653
const LOOP = 2100
const PASS_AT = 90
const FOCAL = 720
const READ_MS = 4200
const ACCELERATE_MS = 2300
const READ_SPEED = 0.06
const FLY_SPEED = 2.25
const FLY_BOOST = 1.65
const ACCENTS = ['#94cfee', '#e8c58d', '#a8d8b9', '#9dbce9', '#f1b4ce', '#bfbcf4', '#dcad9e', '#d8d499', '#c9b1f2', '#e1a7d7', '#78c8e2', '#b9a9f3']

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

function wrapZ(z: number, travel: number, recycle: boolean) {
  let zWorld = z + travel
  if (!recycle) return zWorld
  const start = PASS_AT - LOOP
  let offset = (zWorld - start) % LOOP
  if (offset < 0) offset += LOOP
  return start + offset
}

function project(x: number, y: number, z: number, rx: number, ry: number, travel = 0, recycle = true) {
  const zWorld = wrapZ(z, travel, recycle)
  const denom = FOCAL - zWorld
  const passed = zWorld > PASS_AT || denom <= 36
  const scale = passed ? 0 : clamp(FOCAL / denom, 0.08, 2.8)
  const fadeNear = zWorld > 8 ? clamp(1 - (zWorld - 8) / (PASS_AT - 8), 0, 1) : 1
  const fadeFar = clamp((zWorld - (PASS_AT - LOOP)) / 380, 0, 1)
  return {
    passed,
    opacity: passed ? 0 : fadeNear * fadeFar,
    zIndex: Math.round(4000 + zWorld),
    transform: `translate3d(calc(-50% + ${x * scale}px), calc(-50% + ${y * scale}px), 0) rotateY(${ry}deg) rotateX(${rx}deg) scale(${scale})`,
  }
}

function cardsFromPosts(posts: SearchIntroPost[]): Card[] {
  return posts.flatMap(post => {
    const text = post.text?.trim()
    if (!text) return []
    const handle = (post.handle || '').replace(/^@/, '')
    const author = (post.author || handle || 'Post').replace(/^@/, '').split('·')[0].trim() || 'Post'
    const published = post.publishedAt ? Date.parse(post.publishedAt) : NaN
    return [{
      author,
      handle: handle ? `@${handle}` : '',
      text,
      accent: ACCENTS[Math.abs(Array.from(text).reduce((sum, char) => sum + char.charCodeAt(0), 0)) % ACCENTS.length],
      year: Number.isFinite(published) ? String(new Date(published).getUTCFullYear()) : '',
    }]
  })
}

function placeField(deck: Card[]): PlacedCard[] {
  return Array.from({ length: FIELD_SIZE }, (_, index) => {
    const source = deck[index % deck.length]
    const ring = index / FIELD_SIZE
    const angle = index * GOLDEN
    const z = PASS_AT - 70 - ring * (LOOP - 180) - (index % 5) * 18
    const radius = 170 + (index % 11) * 42 + ring * 70
    return {
      ...source,
      key: `${source.handle}-${index}`,
      x: Math.cos(angle) * radius * 1.55,
      y: Math.sin(angle) * radius * 0.78,
      z,
      rx: Math.sin(angle) * -6,
      ry: Math.cos(angle) * 10,
      width: 292 + (index % 6) * 10,
    }
  })
}

export default function SearchIntro({ phase, className = '', posts = [] }: SearchIntroProps) {
  const fieldRef = useRef<HTMLDivElement>(null)
  const phaseRef = useRef(phase)
  const deck = useMemo(() => {
    const fromPosts = cardsFromPosts(posts)
    return fromPosts.length >= 6 ? fromPosts : CARDS
  }, [posts])
  const items = useMemo(() => placeField(deck), [deck])

  useEffect(() => {
    phaseRef.current = phase
  }, [phase])

  useEffect(() => {
    const field = fieldRef.current
    if (!field) return

    const cards = Array.from(field.querySelectorAll<HTMLElement>('.search-intro-card'))
    const origins = cards.map(card => ({
      x: Number(card.dataset.x),
      y: Number(card.dataset.y),
      z: Number(card.dataset.z),
      rx: Number(card.dataset.rx),
      ry: Number(card.dataset.ry),
    }))
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (motion.matches) return

    let travel = 220
    let last = performance.now()
    const started = last
    let speed = READ_SPEED
    let frame = 0

    const tick = (now: number) => {
      const dt = Math.min(48, now - last)
      last = now
      const resolving = phaseRef.current === 'resolving'
      // Give each newly loaded deck a readable opening before the fly-past.
      const acceleration = clamp((now - started - READ_MS) / ACCELERATE_MS, 0, 1)
      const eased = acceleration * acceleration * (3 - 2 * acceleration)
      const targetSpeed = READ_SPEED + ((resolving ? FLY_SPEED * FLY_BOOST : FLY_SPEED) - READ_SPEED) * eased
      speed += (targetSpeed - speed) * (1 - Math.exp(-dt / 180))
      travel += dt * speed
      const t = now * 0.001
      field.style.setProperty('--sway-x', `${Math.sin(t * 0.28) * 8}px`)
      field.style.setProperty('--sway-y', `${Math.cos(t * 0.22) * 5}px`)

      cards.forEach((card, index) => {
        const origin = origins[index]
        const next = project(origin.x, origin.y, origin.z, origin.rx, origin.ry, travel, true)
        card.classList.toggle('is-passed', next.passed)
        if (next.passed) return
        card.style.opacity = String(next.opacity)
        card.style.zIndex = String(next.zIndex)
        card.style.transform = next.transform
      })

      frame = requestAnimationFrame(tick)
    }

    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [items])

  return (
    <section
      className={`search-intro${phase === 'resolving' ? ' is-resolving' : ''}${className ? ` ${className}` : ''}`.trim()}
      aria-label="Tracing the public conversation"
    >
      <div className="search-intro-stage">
        <div className="search-intro-field" ref={fieldRef}>
          {items.map(item => {
            const start = project(item.x, item.y, item.z, item.rx, item.ry, 220)
            return (
            <article
              key={item.key}
              className="search-intro-card"
              data-x={item.x}
              data-y={item.y}
              data-z={item.z}
              data-rx={item.rx}
              data-ry={item.ry}
              style={{
                '--w': `${item.width}px`,
                '--accent': item.accent,
                opacity: start.opacity,
                zIndex: start.zIndex,
                transform: start.transform,
              } as CSSProperties}
            >
              <header className="search-intro-card-head">
                <span className="search-intro-card-avatar" aria-hidden="true">{item.author[0].toUpperCase()}</span>
                <div className="search-intro-card-names">
                  <strong>{item.author}</strong>
                  <span>{item.handle}</span>
                </div>
              </header>
              <p>{item.text}</p>
              <footer>{item.year}</footer>
            </article>
            )
          })}
        </div>
      </div>
    </section>
  )
}
