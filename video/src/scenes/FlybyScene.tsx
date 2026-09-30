import { AbsoluteFill, Img, staticFile, useCurrentFrame } from 'remotion'
import { clamp01, fade } from '../motion'

type Card = { author: string; handle: string; text: string; year: string; accent: string }
// The same recognizable examples used by Sequitor's live search animation.
const cards: Card[] = [
  { author: 'Jack Dorsey', handle: '@jack', text: 'just setting up my twttr', year: '2006', accent: '#94cfee' },
  { author: 'Kanye West', handle: '@kanyewest', text: 'I hate when I’m on a flight and I wake up with a water bottle next to me like oh great now I gotta be responsible for this water bottle.', year: '2010', accent: '#e8c58d' },
  { author: 'Sohaib Athar', handle: '@ReallyVirtual', text: 'Helicopter hovering above Abbottabad at 1AM (is a rare event).', year: '2011', accent: '#a8d8b9' },
  { author: 'Keith Urbahn', handle: '@keithurbahn', text: 'So I’m told by a reputable person they have killed Osama Bin Laden. Hot damn.', year: '2011', accent: '#9dbce9' },
  { author: 'Horse ebooks', handle: '@Horse_ebooks', text: 'Everything happens so much', year: '2012', accent: '#f1b4ce' },
  { author: 'Curiosity Rover', handle: '@MarsCuriosity', text: 'I’m safely on the surface of Mars. GALE CRATER I AM IN YOU!!! #MSL', year: '2012', accent: '#dcad9e' },
  { author: 'Pope Benedict XVI', handle: '@Pontifex', text: 'Dear friends, I am pleased to get in touch with you through Twitter. Thank you for your generous response. I bless all of you from my heart.', year: '2012', accent: '#d8d499' },
  { author: 'wint', handle: '@dril', text: 'IF THE ZOO BANS ME FOR HOLLERING AT THE ANIMALS I WILL FACE GOD AND WALK BACKWARDS INTO HELL', year: '2012', accent: '#bfbcf4' },
  { author: 'wint', handle: '@dril', text: 'Food $200 Data $150 Rent $800 Candles $3,600 Utility $150 someone who is good at the economy please help me budget this. my family is dying', year: '2013', accent: '#c9b1f2' },
  { author: 'CIA', handle: '@CIA', text: 'We can neither confirm nor deny that this is our first tweet.', year: '2014', accent: '#78c8e2' },
  { author: 'Stephen King', handle: '@StephenKing', text: 'My first tweet. No longer a virgin. Be gentle!', year: '2013', accent: '#e1a7d7' },
  { author: 'Leonard Nimoy', handle: '@TheRealNimoy', text: 'A life is like a garden. Perfect moments can be had, but not preserved, except in memory. LLAP', year: '2015', accent: '#b9a9f3' },
  { author: 'Edward Snowden', handle: '@Snowden', text: 'Can you hear me now?', year: '2015', accent: '#a0dfce' },
  { author: 'Hillary Clinton', handle: '@HillaryClinton', text: 'Delete your account.', year: '2016', accent: '#a2cfed' },
  { author: 'Netflix', handle: '@netflix', text: 'Love is sharing a password.', year: '2017', accent: '#eab5c1' },
  { author: 'Donald J. Trump', handle: '@realDonaldTrump', text: 'Despite the constant negative press covfefe', year: '2017', accent: '#d7e7f0' },
  { author: 'Malala Yousafzai', handle: '@Malala', text: 'Hi, Twitter.', year: '2017', accent: '#94d8c0' },
  { author: 'Elon Musk', handle: '@elonmusk', text: 'Am considering taking Tesla private at $420. Funding secured.', year: '2018', accent: '#c3daa0' },
  { author: 'Twitter', handle: '@Twitter', text: 'hello literally everyone', year: '2021', accent: '#a6bee7' },
  { author: 'Elon Musk', handle: '@elonmusk', text: 'the bird is freed', year: '2022', accent: '#e0c39d' },
  { author: 'Greta Thunberg', handle: '@GretaThunberg', text: 'So ridiculous. Donald must work on his Anger Management problem, then go to a good old fashioned movie with a friend! Chill Donald, Chill!', year: '2020', accent: '#8dd9d2' },
  { author: 'Joe Biden', handle: '@JoeBiden', text: 'It’s a new day in America.', year: '2021', accent: '#94d1ed' },
]

// Pack six depth passes close together so the viewer begins inside a cloud of
// cards. Repeated posts have different positions and rotations in each pass.
const field = Array.from({ length: 132 }, (_, i) => ({ card: cards[i % cards.length], i }))
const position = (i: number) => {
  const angle = i * 2.399963229728653 // golden angle spreads neighbouring cards
  const inset = i % 7 === 2 || i % 7 === 5 ? 0.48 : 1
  const verticalEdge = i % 13 === 3 ? -790 : i % 13 === 9 ? 790 : null
  return {
    x: Math.cos(angle) * (550 + ((i * 197) % 520)) * inset,
    y: verticalEdge ?? Math.sin(angle) * (320 + ((i * 157) % 360)) * inset,
  }
}
// Motion begins at a running pace and continues to accelerate until the last
// card has passed, leaving the full final second empty before the graph.
const travel = (frame: number) => frame <= 80
  ? frame * 6.5
  : 520 + (frame - 80) * 6.5 + 0.25 * (frame - 80) ** 2

const CardFace = ({ card }: { card: Card }) => (
  <div style={{
    width: 480, padding: '24px 25px 22px', boxSizing: 'border-box',
    borderRadius: 17, background: '#101920', border: '1px solid #485d6b',
    boxShadow: '0 18px 55px #000e, inset 0 1px #ffffff0b',
  }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 13 }}>
      <div style={{
        width: 46, height: 46, borderRadius: '50%', overflow: 'hidden',
        background: card.accent, flexShrink: 0,
        border: '1px solid #ffffff35',
      }}><Img src={staticFile(`avatars/${card.handle.slice(1)}.jpg`)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /></div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 750, fontSize: 20, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{card.author}</div>
        <div style={{ color: '#8999a3', fontSize: 17 }}>{card.handle}</div>
      </div>
      <svg width="29" height="29" viewBox="0 0 24 24" aria-label="X" style={{ flexShrink: 0 }}>
        <path fill="#edf4f7" d="M18.901 1.153h3.68L14.54 10.35 24 22.847h-7.406l-5.8-7.586-6.64 7.586H.47l8.6-9.824L0 1.153h7.594l5.243 6.932 6.064-6.932Zm-1.29 19.49h2.04L6.487 3.24H4.3l13.31 17.4Z" />
      </svg>
    </div>
    <div style={{ fontSize: 21, lineHeight: 1.48, marginTop: 22, minHeight: 64, letterSpacing: '-0.015em' }}>{card.text}</div>
    <div style={{ display: 'flex', gap: 37, color: '#738691', fontSize: 16, marginTop: 26, borderTop: '1px solid #24343e', paddingTop: 14 }}>
      <span>{card.year}</span><span>♡</span><span>↻</span><span>↗</span>
    </div>
  </div>
)

export const FlybyScene = () => {
  const frame = useCurrentFrame()
  const distance = travel(frame)
  return (
    <AbsoluteFill style={{
      background: 'radial-gradient(ellipse 1000px 720px at 50% 50%, #07121b, #000 78%)',
      overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', inset: 0, perspective: 1100, perspectiveOrigin: '50% 50%' }}>
        {field.map(({ card, i }) => {
          const z = 85 - i * 52 + distance
          // By this depth the card is completely outside the viewport. Cull it
          // only after it has flown past an edge, never while still on screen.
          if (z >= 390) return null
          const scale = Math.min(2.3, 1000 / Math.max(400, 1000 - z))
          const opacity = clamp01((z + 2450) / 450) * fade(frame, 2, 16)
          const sway = Math.sin((frame + i * 21) * 0.021) * 10
          const { x, y } = position(i)
          const rayLength = Math.hypot(x / 960, y / 540) || 1
          const pass = Math.max(0, (z - 80) / 310)
          const outward = 2500 * pass * pass
          return <div key={i} style={{
            position: 'absolute',
            left: 960 + x * scale + (x / 960 / rayLength) * outward,
            top: 540 + (y + sway) * scale + (y / 540 / rayLength) * outward,
            opacity, zIndex: Math.round(z + 2000),
            transform: `translate(-50%, -50%) rotateX(${(i % 3 - 1) * 5 + Math.sin(frame * .012 + i) * 2}deg) rotateY(${(i % 4 - 1.5) * 7 + Math.sin(frame * .008 + i) * 3}deg) scale(${scale})`,
            filter: `blur(${Math.max(0, -z - 1100) / 500}px)`,
          }}><CardFace card={card} /></div>
        })}
      </div>
      <AbsoluteFill style={{ background: '#000', opacity: fade(frame, 230, 239) }} />
    </AbsoluteFill>
  )
}
