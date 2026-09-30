import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion'
import { easeOut, fade, palette } from '../motion'

export const LogoScene = () => {
  const frame = useCurrentFrame()
  const exit = 1 - fade(frame, 91, 104)
  const trace = easeOut((frame - 3) / 39)
  const letters = fade(frame, 24, 62)
  const dot = fade(frame, 5, 22)
  return (
    <AbsoluteFill style={{ background: palette.black, opacity: exit, overflow: 'hidden' }}>
      <AbsoluteFill style={{
        background: 'radial-gradient(ellipse 650px 270px at 50% 51%, #13324374, transparent 70%)',
        opacity: fade(frame, 0, 48),
      }} />
      <svg width="1920" height="1080" viewBox="0 0 1920 1080" style={{ position: 'absolute', inset: 0 }}>
        <defs>
          <linearGradient id="trace" x1="0" x2="1">
            <stop stopColor="#bda7fc" />
            <stop offset=".6" stopColor="#9bddf4" />
            <stop offset="1" stopColor="#74d7e4" />
          </linearGradient>
          <filter id="blur"><feGaussianBlur stdDeviation="9" /></filter>
        </defs>
        <path d="M 455 580 C 660 580 690 470 850 510 S 1080 585 1460 506"
          stroke="url(#trace)" strokeWidth="14" fill="none" filter="url(#blur)"
          opacity={0.75 * (1 - fade(frame, 55, 80))}
          pathLength="100" strokeDasharray="100" strokeDashoffset={100 * (1 - trace)} />
        <path d="M 455 580 C 660 580 690 470 850 510 S 1080 585 1460 506"
          stroke="url(#trace)" strokeWidth="2.5" fill="none"
          opacity={1 - fade(frame, 55, 82)}
          pathLength="100" strokeDasharray="100" strokeDashoffset={100 * (1 - trace)} />
      </svg>
      <div style={{
        position: 'absolute', left: 435 + 1010 * trace, top: 508 + 12 * Math.sin(trace * Math.PI),
        width: 15, height: 15, borderRadius: '50%', background: palette.cyan,
        boxShadow: '0 0 12px #b0edff, 0 0 45px #67c5ed, 0 0 100px #79cbed',
        opacity: dot * (1 - fade(frame, 56, 78)),
      }} />
      <div style={{
        position: 'absolute', width: '100%', top: 390, textAlign: 'center',
        fontWeight: 800, fontSize: 162, letterSpacing: '-0.085em', lineHeight: 1,
        opacity: letters, transform: `translateY(${interpolate(frame, [23, 62], [35, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })}px)`,
        textShadow: '0 0 55px #9ad9f536',
      }}>sequitor<span style={{ color: palette.cyan }}>.</span></div>
      <div style={{
        position: 'absolute', width: '100%', top: 612, textAlign: 'center',
        fontSize: 27, letterSpacing: '0.24em', fontWeight: 550, color: '#a8d6e7',
        opacity: fade(frame, 58, 78),
      }}>FOLLOW THE CONVERSATION</div>
      <div style={{
        position: 'absolute', left: 662, top: 696, width: 596, height: 1,
        background: 'linear-gradient(90deg, transparent, #5a93ae, transparent)',
        opacity: fade(frame, 65, 85) * 0.65,
      }} />
    </AbsoluteFill>
  )
}
