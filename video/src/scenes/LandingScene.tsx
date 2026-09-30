import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion'
import rawData from '../data.json'
import type { DemoData } from '../types'
import { easeInOut, easeOut, fade, palette } from '../motion'

const data = rawData as DemoData
const typed = data.seedText.split('\n')[0]

export const LandingScene = () => {
  const frame = useCurrentFrame()
  const arrive = fade(frame, 0, 24)
  const typedCount = Math.floor(interpolate(frame, [30, 190], [0, typed.length], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }))
  const cursor = frame < 195 && frame % 18 < 12
  const click = easeOut((frame - 195) / 12)
  const genie = easeInOut((frame - 210) / 29)
  const wordmarkY = interpolate(frame, [0, 70], [16, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <AbsoluteFill style={{ background: '#000', overflow: 'hidden' }}>
      <AbsoluteFill style={{
        background: 'radial-gradient(ellipse 900px 470px at 50% 53%, #0b1b2777, transparent 75%)',
        opacity: arrive * (1 - genie),
      }} />
      <div style={{
        position: 'absolute', top: 118, width: '100%', textAlign: 'center',
        fontWeight: 800, fontSize: 64, letterSpacing: '-0.08em',
        opacity: arrive * (1 - genie),
        transform: `translateY(${wordmarkY}px)`,
      }}>sequitor<span style={{ color: palette.cyan }}>.</span></div>
      <div style={{
        position: 'absolute', top: 201, width: '100%', textAlign: 'center',
        color: '#a5b6c1', fontSize: 25, opacity: fade(frame, 12, 38) * (1 - genie),
      }}>Start with a post. See the conversation around it.</div>
      <div style={{
        position: 'absolute', left: 480, top: 315, width: 960, height: 410,
        transformOrigin: '50% 50%',
        transform: `translate(${660 * genie}px, ${-340 * genie}px) skewX(${-27 * genie}deg) scale(${1 - 0.96 * genie}, ${1 - 0.985 * genie})`,
        opacity: arrive * (1 - easeOut((genie - 0.77) / 0.23)),
        filter: `blur(${genie * 15}px)`,
      }}>
        <div style={{
          height: '100%', padding: '35px 42px', boxSizing: 'border-box', borderRadius: 28,
          background: '#080d12', border: '1px solid #2c3e49',
          boxShadow: `0 30px 100px #000b, 0 0 ${50 + click * 50}px #83c8e412`,
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 15, color: '#8fa6b3', fontSize: 22 }}>
            <span style={{ color: palette.cyan, fontSize: 29 }}>↗</span>
            <span>TRACE THIS POST</span>
            <span style={{ marginLeft: 'auto', color: '#718c9c', fontSize: 18 }}>X / TWITTER</span>
          </div>
          <div style={{
            marginTop: 28, flex: 1, fontSize: 35, lineHeight: 1.5,
            color: palette.text, fontWeight: 450, letterSpacing: '-0.025em',
          }}>
            {typed.slice(0, typedCount)}
            {cursor && <span style={{ display: 'inline-block', width: 3, height: 37, verticalAlign: '-5px', background: palette.cyan, marginLeft: 3 }} />}
            {typedCount === 0 && <span style={{ color: '#557080' }}>Paste a post or enter a topic…</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid #25313a', paddingTop: 22 }}>
            <span style={{ color: '#7995a5', fontSize: 19 }}>Find the reference · See the responses</span>
            <div style={{
              padding: '14px 30px', borderRadius: 999, background: palette.cyan, color: '#07121a',
              fontSize: 23, fontWeight: 700, transform: `scale(${1 - 0.08 * click})`,
              boxShadow: `0 0 ${25 + click * 65}px #94d8f3${click > 0 ? 'aa' : '44'}`,
            }}>Explore <span style={{ marginLeft: 10 }}>↗</span></div>
          </div>
        </div>
      </div>
      {genie > 0 && (
        <svg width="1920" height="1080" style={{ position: 'absolute', inset: 0, opacity: Math.sin(genie * Math.PI) * 0.88 }}>
          {Array.from({ length: 12 }, (_, i) => {
            const y = 412 + i * 17
            return <path key={i} d={`M ${750 + i * 28} ${y} C ${1140 + i * 10} ${y - 170} 1300 235 1640 195`}
              stroke={i % 3 === 0 ? palette.violet : palette.cyan} strokeWidth={i % 4 === 0 ? 3 : 1.4}
              fill="none" strokeDasharray="28 48" strokeDashoffset={-genie * (500 + i * 30)} />
          })}
        </svg>
      )}
      <div style={{
        position: 'absolute', left: 1628, top: 184, width: 25, height: 25, borderRadius: 99,
        background: palette.cyan, boxShadow: '0 0 24px #9ce4ff, 0 0 100px #6ac7ef',
        opacity: genie * (1 - fade(frame, 220, 239)),
        transform: `scale(${0.2 + genie * 1.2})`,
      }} />
    </AbsoluteFill>
  )
}
