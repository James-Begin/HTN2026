import { useEffect, useMemo, useRef } from 'react'
import type { CSSProperties } from 'react'
import './search-intro.css'

export type SearchIntroPhase = 'idle' | 'searching' | 'resolving'
export type SearchIntroProps = { phase: SearchIntroPhase; className?: string }

type Card = { author: string; handle: string; text: string; accent: string; year: string }
type PlacedCard = Card & {
  key: string
  x: number
  y: number
  z: number
  rx: number
  ry: number
  width: number
  delay: number
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

const FIELD_SIZE = 110
const NEAR_COUNT = 64
const GOLDEN = 2.399963229728653
const CRUISE_MS = 6500
const FLY_MS = 1800
const CRUISE_START = 20
const CRUISE_TRAVEL = 820
const FLY_TRAVEL = 3800
const PASS_Z = 120

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))
const easeInCubic = (value: number) => value * value * value

function placeField(): PlacedCard[] {
  return Array.from({ length: FIELD_SIZE }, (_, index) => {
    const source = CARDS[index % CARDS.length]
    const near = index < NEAR_COUNT
    const local = near ? index / Math.max(NEAR_COUNT - 1, 1) : (index - NEAR_COUNT) / Math.max(FIELD_SIZE - NEAR_COUNT - 1, 1)
    const angle = index * GOLDEN
    const z = near ? -200 - local * 780 : -1040 - local * 1680
    const radius = near
      ? 92 + (index % 8) * 22 + local * 64
      : 84 + (index % 6) * 16
    return {
      ...source,
      key: `${source.handle}-${index}`,
      x: Math.cos(angle) * radius * 1.18,
      y: Math.sin(angle) * radius * 0.72,
      z,
      rx: Math.sin(angle) * -6,
      ry: Math.cos(angle) * 10,
      width: 300 + (index % 7) * 10,
      delay: 0,
    }
  })
}

export default function SearchIntro({ phase, className = '' }: SearchIntroProps) {
  const fieldRef = useRef<HTMLDivElement>(null)
  const phaseRef = useRef(phase)
  const items = useMemo(placeField, [])

  useEffect(() => {
    phaseRef.current = phase
  }, [phase])

  useEffect(() => {
    const field = fieldRef.current
    if (!field) return

    const cards = Array.from(field.querySelectorAll<HTMLElement>('.search-intro-card'))
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (motion.matches) {
      field.style.setProperty('--travel', '0px')
      field.style.setProperty('--spread', '1')
      field.style.setProperty('--sway-x', '0px')
      field.style.setProperty('--sway-y', '0px')
      field.style.setProperty('--fly', '0')
      return
    }

    const mountedAt = performance.now()
    let flyStartedAt = 0
    let travelWhenFly = 0
    let frame = 0

    const tick = (now: number) => {
      const resolving = phaseRef.current === 'resolving'
      let travel = 0
      let spread = 1
      let fly = 0

      if (resolving) {
        if (!flyStartedAt) {
          flyStartedAt = now
          travelWhenFly = CRUISE_START + clamp((now - mountedAt) / CRUISE_MS, 0, 1) * CRUISE_TRAVEL
        }
        fly = easeInCubic(clamp((now - flyStartedAt) / FLY_MS, 0, 1))
        travel = travelWhenFly + fly * FLY_TRAVEL
        spread = 1 + fly * 2.15
        field.style.setProperty('--sway-x', '0px')
        field.style.setProperty('--sway-y', '0px')
      } else if (phaseRef.current === 'searching') {
        travel = CRUISE_START + clamp((now - mountedAt) / CRUISE_MS, 0, 1) * CRUISE_TRAVEL
        const t = now * 0.001
        field.style.setProperty('--sway-x', `${Math.sin(t * 0.17) * 14}px`)
        field.style.setProperty('--sway-y', `${Math.cos(t * 0.13) * 9}px`)
      }

      field.style.setProperty('--travel', `${travel}px`)
      field.style.setProperty('--spread', String(spread))
      field.style.setProperty('--fly', String(fly))

      for (const card of cards) {
        const depth = Number(card.dataset.z)
        card.classList.toggle('is-passed', depth + travel > PASS_Z)
      }

      frame = requestAnimationFrame(tick)
    }

    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [])

  return (
    <section
      className={`search-intro${phase === 'resolving' ? ' is-resolving' : ''}${className ? ` ${className}` : ''}`.trim()}
      aria-label="Tracing the public conversation"
    >
      <div className="search-intro-stage">
        <div className="search-intro-field" ref={fieldRef}>
          {items.map(item => (
            <article
              key={item.key}
              className="search-intro-card"
              data-z={item.z}
              style={{
                '--x': `${item.x}px`,
                '--y': `${item.y}px`,
                '--z': `${item.z}px`,
                '--rx': `${item.rx}deg`,
                '--ry': `${item.ry}deg`,
                '--w': `${item.width}px`,
                '--delay': `${item.delay}ms`,
                '--accent': item.accent,
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
          ))}
        </div>
      </div>
    </section>
  )
}
