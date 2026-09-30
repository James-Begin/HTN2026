import { AbsoluteFill, Composition, Sequence, useCurrentFrame } from 'remotion'
import '@fontsource-variable/inter/wght.css'
import { LogoScene } from './scenes/LogoScene'
import { LandingScene } from './scenes/LandingScene'
import { FlybyScene } from './scenes/FlybyScene'
import { GraphScene } from './scenes/GraphScene'

const INTRO = 105
const LANDING = 240
const FLYBY = 270
const GRAPH = 750

const FilmGrain = () => {
  const frame = useCurrentFrame()
  return (
    <AbsoluteFill style={{
      pointerEvents: 'none',
      opacity: 0.055,
      backgroundImage: 'radial-gradient(#90b6c8 0.5px, transparent 0.6px)',
      backgroundSize: '7px 7px',
      backgroundPosition: `${frame % 7}px ${(frame * 3) % 7}px`,
      mixBlendMode: 'screen',
    }} />
  )
}

export const SequitorDemo = () => (
  <AbsoluteFill style={{ backgroundColor: '#020508', fontFamily: 'Inter Variable, Inter, Arial, sans-serif', color: '#eef7fb' }}>
    <Sequence from={0} durationInFrames={INTRO}><LogoScene /></Sequence>
    <Sequence from={INTRO} durationInFrames={LANDING}><LandingScene /></Sequence>
    <Sequence from={INTRO + LANDING} durationInFrames={FLYBY}><FlybyScene /></Sequence>
    <Sequence from={INTRO + LANDING + FLYBY} durationInFrames={GRAPH}><GraphScene /></Sequence>
    <FilmGrain />
  </AbsoluteFill>
)

export const Root = () => (
  <Composition id="SequitorDemo" component={SequitorDemo} durationInFrames={INTRO + LANDING + FLYBY + GRAPH} fps={30} width={1920} height={1080} />
)
