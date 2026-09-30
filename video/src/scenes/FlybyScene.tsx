import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion'
import { clamp01, easeOut, fade, palette } from '../motion'

type Card = { author: string; handle: string; text: string; year: string; accent: string }
// The same recognizable examples used by Sequitor's live search animation.
const cards: Card[] = [
  { author: 'Jack Dorsey', handle: '@jack', text: 'just setting up my twttr', year: '2006', accent: '#94cfee' },
  { author: 'Kanye West', handle: '@kanyewest', text: 'I hate when I’m on a flight and I wake up with a water bottle next to me like oh great now I gotta be responsible for this water bottle.', year: '2010', accent: '#e8c58d' },
  { author: 'Horse ebooks', handle: '@Horse_ebooks', text: 'Everything happens so much', year: '2012', accent: '#f1b4ce' },
  { author: 'Curiosity Rover', handle: '@MarsCuriosity', text: 'I’m safely on the surface of Mars. GALE CRATER I AM IN YOU!!! #MSL', year: '2012', accent: '#dcad9e' },
  { author: 'wint', handle: '@dril', text: 'IF THE ZOO BANS ME FOR HOLLERING AT THE ANIMALS I WILL FACE GOD AND WALK BACKWARDS INTO HELL', year: '2012', accent: '#bfbcf4' },
  { author: 'CIA', handle: '@CIA', text: 'We can neither confirm nor deny that this is our first tweet.', year: '2014', accent: '#78c8e2' },
  { author: 'Stephen King', handle: '@StephenKing', text: 'My first tweet. No longer a virgin. Be gentle!', year: '2013', accent: '#e1a7d7' },
  { author: 'Edward Snowden', handle: '@Snowden', text: 'Can you hear me now?', year: '2015', accent: '#a0dfce' },
  { author: 'Hillary Clinton', handle: '@HillaryClinton', text: 'Delete your account.', year: '2016', accent: '#a2cfed' },
  { author: 'Netflix', handle: '@netflix', text: 'Love is sharing a password.', year: '2017', accent: '#eab5c1' },
  { author: 'Donald J. Trump', handle: '@realDonaldTrump', text: 'Despite the constant negative press covfefe', year: '2017', accent: '#d7e7f0' },
  { author: 'Malala Yousafzai', handle: '@Malala', text: 'Hi, Twitter.', year: '2017', accent: '#94d8c0' },
  { author: 'Elon Musk', handle: '@elonmusk', text: 'Am considering taking Tesla private at $420. Funding secured.', year: '2018', accent: '#c3daa0' },
  { author: 'Twitter', handle: '@Twitter', text: 'hello literally everyone', year: '2021', accent: '#a6bee7' },
  { author: 'Elon Musk', handle: '@elonmusk', text: 'the bird is freed', year: '2022', accent: '#e0c39d' },
  { author: 'Greta Thunberg', handle: '@GretaThunberg', text: 'So ridiculous. Donald must work on his Anger Management problem, then go to a good old fashioned movie with a friend! Chill Donald, Chill!', year: '2020', accent: '#8dd9d2' },
]

const xPositions = [-420, 445, 100, -570, 570, -230, 460, -590, 160, 650, -330, 320, -460, 530, -100, 390]
const yPositions = [-165, 130, 255, 170, -230, -320, -95, -140, -250, 280, 110, 20, 290, -270, -30, 210]
const travel = (frame: number) => frame <= 105 ? frame * 0.65 : 68 + (frame - 105) * 0.65 + 0.115 * (frame - 105) ** 2

const CardFace = ({ card }: { card: Card }) => (
  <div style={{
    width: 448, padding: '24px 25px 22px', boxSizing: 'border-box',
    borderRadius: 17, background: '#0c1116', border: '1px solid #33414d',
    boxShadow: '0 18px 55px #000e, inset 0 1px #ffffff0b',
  }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 13 }}>
      <div style={{
        width: 46, height: 46, borderRadius: '50%', display: 'grid', placeItems: 'center',
        background: card.accent, color: '#081015', fontSize: 21, fontWeight: 800, flexShrink: 0,
      }}>{card.author[0]}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 750, fontSize: 20, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{card.author}</div>
        <div style={{ color: '#8999a3', fontSize: 17 }}>{card.handle}</div>
      </div>
      <div style={{ fontSize: 27, color: '#c7d1d8', fontWeight: 450 }}>𝕏</div>
    </div>
    <div style={{ fontSize: 21, lineHeight: 1.48, marginTop: 22, minHeight: 64, letterSpacing: '-0.015em' }}>{card.text}</div>
    <div style={{ display: 'flex', gap: 37, color: '#738691', fontSize: 16, marginTop: 26, borderTop: '1px solid #24343e', paddingTop: 14 }}>
      <span>{card.year}</span><span>♡</span><span>↻</span><span>↗</span>
    </div>
  </div>
)

export const FlybyScene = () => {
  const frame = useCurrentFrame()
  const rush = easeOut((frame - 100) / 135)
  const exit = 1 - fade(frame, 240, 269)
  const distance = travel(frame)
  return (
    <AbsoluteFill style={{
      background: 'radial-gradient(ellipse 1000px 720px at 50% 50%, #07121b, #000 78%)',
      overflow: 'hidden',
    }}>
      <svg width="1920" height="1080" style={{ position: 'absolute', inset: 0, opacity: 0.3 * rush * exit }}>
        {Array.from({ length: 45 }, (_, i) => {
          const angle = i * 2.3999632
          const r = 150 + ((i * 173) % 400)
          const x = 960 + Math.cos(angle) * r
          const y = 540 + Math.sin(angle) * r
          const length = 30 + 220 * rush
          return <line key={i} x1={x} y1={y} x2={x + Math.cos(angle) * length} y2={y + Math.sin(angle) * length}
            stroke={i % 4 === 0 ? palette.violet : palette.cyan} strokeWidth={i % 5 === 0 ? 2.4 : 1.2} />
        })}
      </svg>
      <div style={{ position: 'absolute', inset: 0, perspective: 1100, perspectiveOrigin: '50% 50%' }}>
        {cards.map((card, i) => {
          const z = -140 - i * 170 + distance
          const scale = Math.min(2.3, 1000 / Math.max(400, 1000 - z))
          const visible = clamp01((z + 1750) / 300) * clamp01((320 - z) / 190)
          const opacity = visible * fade(frame, 6, 29) * exit
          const sway = Math.sin((frame + i * 21) * 0.021) * 10
          return <div key={i} style={{
            position: 'absolute', left: 960 + xPositions[i] * scale, top: 540 + (yPositions[i] + sway) * scale,
            opacity, zIndex: Math.round(z + 2000),
            transform: `translate(-50%, -50%) rotateX(${(i % 3 - 1) * 5 + Math.sin(frame * .012 + i) * 2}deg) rotateY(${(i % 4 - 1.5) * 7 + Math.sin(frame * .008 + i) * 3}deg) scale(${scale})`,
            filter: `blur(${Math.max(0, -z - 1100) / 500}px)`,
          }}><CardFace card={card} /></div>
        })}
      </div>
      <div style={{
        position: 'absolute', left: 1640, top: 195, width: 20, height: 20,
        borderRadius: '50%', background: palette.cyan, boxShadow: '0 0 55px #90e8ff',
        opacity: 1 - fade(frame, 0, 20), transform: `scale(${interpolate(frame, [0, 20], [1, 0.2], { extrapolateRight: 'clamp' })})`,
      }} />
      <AbsoluteFill style={{ background: '#000', opacity: fade(frame, 252, 269) }} />
    </AbsoluteFill>
  )
}
