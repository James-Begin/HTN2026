import { AbsoluteFill, useCurrentFrame } from 'remotion'
import rawData from '../data.json'
import type { DemoData, Node } from '../types'
import { clamp01, easeInOut, easeOut, fade, palette } from '../motion'

const data = rawData as DemoData
const byId = new Map(data.nodes.map((node) => [node.id, node]))

const birth = (order: number) => {
  if (order === 0) return 16
  if (order <= 5) return 74 + (order - 1) * 23
  if (order <= 35) return 178 + (order - 6) * 5
  return 336 + (order - 36) * 1.42
}

const nodeColor = (node: Node) =>
  node.order === 0 ? '#e9faff' : node.branch === 'humor' ? palette.violet : node.cosine > 0.65 ? palette.teal : palette.cyan

type ProjectedNode = { x: number; y: number; scale: number }

const mix = (a: number, b: number, t: number) => a + (b - a) * t
const orbitAt = (frame: number) => {
  // The original flat view remains intact while posts arrive. Afterwards the
  // camera arcs to either side, revealing the saved semantic Y coordinate.
  const yaw = frame < 570
    ? mix(0, 0.50, easeInOut((frame - 505) / 65))
    : frame < 650
      ? mix(0.50, -0.38, easeInOut((frame - 570) / 80))
      : mix(-0.38, 0, easeInOut((frame - 650) / 70))
  const pitch = frame < 570
    ? mix(0, -0.19, easeInOut((frame - 505) / 65))
    : frame < 650
      ? mix(-0.19, 0.14, easeInOut((frame - 570) / 80))
      : mix(0.14, 0, easeInOut((frame - 650) / 70))
  const blend = easeInOut((frame - 505) / 30) * (1 - easeInOut((frame - 690) / 30))
  return { yaw, pitch, blend }
}

const projectPoint = (x: number, y: number, semanticY: number, orbit: ReturnType<typeof orbitAt>): ProjectedNode => {
  const worldX = x - 850
  const worldY = y - 515
  const worldZ = semanticY * 750
  const yawX = worldX * Math.cos(orbit.yaw) + worldZ * Math.sin(orbit.yaw)
  const yawZ = worldZ * Math.cos(orbit.yaw) - worldX * Math.sin(orbit.yaw)
  const pitchY = worldY * Math.cos(orbit.pitch) - yawZ * Math.sin(orbit.pitch)
  const pitchZ = worldY * Math.sin(orbit.pitch) + yawZ * Math.cos(orbit.pitch)
  const perspective = 1700 / (1700 - pitchZ)
  return {
    x: mix(x, 850 + yawX * perspective, orbit.blend),
    y: mix(y, 515 + pitchY * perspective, orbit.blend),
    scale: mix(1, perspective, orbit.blend),
  }
}
const projectNode = (node: Node, orbit: ReturnType<typeof orbitAt>) =>
  projectPoint(node.x, node.y, node.semanticY, orbit)

const hoverBeats = [
  { node: data.nodes[1], start: 540, end: 580 }, // the joke
  { node: data.nodes[2], start: 600, end: 645 }, // the industry response
  { node: data.nodes[4], start: 665, end: 705 }, // the wider reaction
]

const TimeChart = ({ frame }: { frame: number }) => {
  const inProgress = fade(frame, 386, 476)
  const max = Math.max(1, ...data.buckets.map((bucket) => bucket.count))
  return (
    <div style={{
      position: 'absolute', bottom: 0, left: 0, width: 1495, height: 153,
      background: 'linear-gradient(180deg, #07131b00, #09131b 25%)',
      borderTop: '1px solid #21333e', padding: '17px 44px 19px',
      boxSizing: 'border-box', opacity: fade(frame, 365, 445),
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, color: '#a6bdca' }}>
        <span style={{ fontWeight: 650 }}>Activity over time</span>
        <span style={{ color: '#7d9bab' }}>Hour&nbsp;&nbsp;&nbsp; <b style={{ color: palette.cyan }}>Day</b>&nbsp;&nbsp;&nbsp; Month</span>
      </div>
      <div style={{ display: 'flex', gap: 6, height: 70, alignItems: 'end', marginTop: 12 }}>
        {data.buckets.map((bucket, i) => {
          const stagger = clamp01((frame - 380 - i * 9) / 45)
          const height = Math.sqrt(bucket.count / max) * 67 * easeOut(stagger) * inProgress
          return <div key={bucket.day} style={{
            flex: 1, height: Math.max(2, height), borderRadius: '3px 3px 0 0',
            background: i === 0 ? '#b8e7fa' : '#83bad2', opacity: i === 0 ? 0.92 : 0.65,
            boxShadow: i === 0 ? '0 0 28px #8fd4ed44' : undefined,
          }} />
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#718b9b', marginTop: 4 }}>
        <span>Sep 12</span><span>Sep 19</span>
      </div>
    </div>
  )
}

const PostCard = ({ node, index, frame, active }: { node: Node; index: number; frame: number; active: boolean }) => {
  const entrance = fade(frame, 325 + index * 34, 361 + index * 34)
  return (
    <div style={{
      background: active ? '#142431' : '#0d1820',
      border: `1px solid ${active ? nodeColor(node) : '#263c49'}`, borderRadius: 9,
      padding: '16px 18px', marginBottom: 11, opacity: entrance,
      transform: `translateY(${(1 - entrance) * 20}px)`,
      boxShadow: active ? `0 0 24px ${nodeColor(node)}24` : undefined,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{
          width: 34, height: 34, borderRadius: '50%', display: 'grid', placeItems: 'center',
          background: nodeColor(node) + '30', color: nodeColor(node), fontWeight: 800, fontSize: 16,
        }}>{node.author[0]}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, color: '#e6f3fb', fontSize: 16, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', maxWidth: 275 }}>{node.author}</div>
          <div style={{ color: '#7793a5', fontSize: 13 }}>{node.handle ? `@${node.handle.replace(/^@/, '')}` : 'X post'}</div>
        </div>
      </div>
      <div style={{ color: '#c4d8e4', fontSize: 16, lineHeight: 1.42, marginTop: 11, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{node.text}</div>
      <div style={{ color: '#7295a6', fontSize: 13, marginTop: 12 }}>{node.branch === 'humor' ? 'HUMOR' : node.quotedPostId ? 'QUOTE' : node.parentId ? 'REPLY' : 'RELATED POST'} <span style={{ float: 'right' }}>♡ {node.likes.toLocaleString()}</span></div>
    </div>
  )
}

const Sidebar = ({ frame, visibleCount, activeId }: { frame: number; visibleCount: number; activeId: string | null }) => {
  const inProgress = fade(frame, 270, 420)
  const posts = data.nodes.slice(1, 7)
  return (
    <div style={{
      position: 'absolute', right: 0, top: 0, width: 425, height: 1080,
      boxSizing: 'border-box', padding: '36px 28px',
      borderLeft: '1px solid #29404d', background: '#0b141c',
      opacity: inProgress, transform: `translateX(${(1 - inProgress) * 60}px)`,
      overflow: 'hidden',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ color: '#e8f5fb', fontSize: 27, fontWeight: 700 }}>Lineage</div>
        <div style={{ color: palette.cyan, fontSize: 14 }}>Links on&nbsp;&nbsp;◉</div>
      </div>
      <div style={{ color: '#91acba', fontSize: 15, marginTop: 8, lineHeight: 1.4 }}>AI industry pacing and evaluation plan</div>
      <div style={{ marginTop: 28, paddingBottom: 13, borderBottom: '1px solid #223540', fontSize: 13, letterSpacing: '.1em', color: '#81a4b8' }}>REFERENCE POST</div>
      <div style={{
        marginTop: 13, marginBottom: 25, padding: '18px 18px 20px', borderRadius: 9,
        border: '1px solid #40647a', boxShadow: '0 0 28px #77d8f01b', background: '#101e28',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          <div style={{ width: 37, height: 37, borderRadius: 99, background: '#b6e6f8', color: '#0d2631', display: 'grid', placeItems: 'center', fontWeight: 800 }}>D</div>
          <div><div style={{ fontSize: 17, fontWeight: 750 }}>Dario Amodei</div><div style={{ color: '#8aaabd', fontSize: 13 }}>@DarioAmodei</div></div>
        </div>
        <div style={{ fontSize: 16, color: '#d6e7f0', lineHeight: 1.45, marginTop: 14 }}>
          We Must Pace the Frontier: I’ve written a new essay on why the AI industry should slow down, with a three-part plan for doing so.
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#9ebdcd', fontSize: 14, paddingBottom: 12 }}>
        <strong style={{ letterSpacing: '.08em' }}>CAPTURED POSTS</strong><span>{visibleCount}</span>
      </div>
      {posts.map((post, i) => <PostCard node={post} index={i} frame={frame} active={activeId === post.id} key={post.id} />)}
    </div>
  )
}

const HoverPreview = ({ node, point, opacity }: { node: Node; point: ProjectedNode; opacity: number }) => {
  const color = nodeColor(node)
  const left = Math.max(36, Math.min(1070, point.x + 34))
  const top = Math.max(145, Math.min(690, point.y - 230))
  return (
    <div style={{
      position: 'absolute', left, top, width: 420, zIndex: 12,
      boxSizing: 'border-box', padding: '18px 20px 17px',
      border: `1px solid ${color}9b`, borderRadius: 13,
      background: '#101e28', boxShadow: `0 16px 48px #000c, 0 0 36px ${color}22`,
      opacity, transform: `translateY(${(1 - opacity) * 14}px) scale(${0.985 + opacity * 0.015})`,
      pointerEvents: 'none',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{
          width: 38, height: 38, borderRadius: '50%', display: 'grid', placeItems: 'center',
          background: `${color}2a`, color, fontWeight: 800, fontSize: 19,
        }}>{node.author[0]}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 750, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{node.author}</div>
          <div style={{ fontSize: 13, color: '#8ca9b9' }}>@{node.handle.replace(/^@/, '')}</div>
        </div>
        <svg width="23" height="23" viewBox="0 0 24 24" aria-label="X">
          <path fill="#dfedf3" d="M18.901 1.153h3.68L14.54 10.35 24 22.847h-7.406l-5.8-7.586-6.64 7.586H.47l8.6-9.824L0 1.153h7.594l5.243 6.932 6.064-6.932Zm-1.29 19.49h2.04L6.487 3.24H4.3l13.31 17.4Z" />
        </svg>
      </div>
      <div style={{
        fontSize: 16, color: '#e4eff5', lineHeight: 1.45, marginTop: 15,
        display: '-webkit-box', WebkitLineClamp: 6, WebkitBoxOrient: 'vertical', overflow: 'hidden',
      }}>{node.text}</div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #2b4350',
        marginTop: 17, paddingTop: 12, fontSize: 13, color: '#8aa9ba',
      }}><span>{node.branch === 'humor' ? 'HUMOR' : node.quotedPostId ? 'QUOTE' : node.parentId ? 'REPLY' : 'RELATED POST'}</span><span>♡ {node.likes.toLocaleString()}</span></div>
    </div>
  )
}

export const GraphScene = () => {
  const frame = useCurrentFrame()
  const camera = easeInOut((frame - 52) / 447)
  const scale = 2.48 + (1 - 2.48) * camera
  const tx = (960 - 310 * 2.48) * (1 - camera)
  const ty = (535 - 515 * 2.48) * (1 - camera)
  const orbit = orbitAt(frame)
  const projected = new Map(data.nodes.map((node) => [node.id, projectNode(node, orbit)]))
  const screenPoint = (node: Node): ProjectedNode => {
    const point = projected.get(node.id)!
    return { x: tx + point.x * scale, y: ty + point.y * scale, scale: point.scale * scale }
  }
  const axisStart = projectPoint(310, 515, 0, orbit)
  const axisEnd = projectPoint(1425, 515, 0, orbit)
  const beat = hoverBeats.find((item) => frame >= item.start && frame < item.end)
  const activeId = beat?.node.id ?? null
  const hoverOpacity = beat
    ? fade(frame, beat.start, beat.start + 9) * (1 - fade(frame, beat.end - 9, beat.end))
    : 0
  const [first, second, third] = hoverBeats.map((item) => screenPoint(item.node))
  const cursor = frame < 540
    ? { x: mix(830, first.x, easeInOut((frame - 510) / 30)), y: mix(800, first.y, easeInOut((frame - 510) / 30)) }
    : frame < 580 ? first
      : frame < 600
        ? { x: mix(first.x, second.x, easeInOut((frame - 580) / 20)), y: mix(first.y, second.y, easeInOut((frame - 580) / 20)) }
        : frame < 645 ? second
          : frame < 665
            ? { x: mix(second.x, third.x, easeInOut((frame - 645) / 20)), y: mix(second.y, third.y, easeInOut((frame - 645) / 20)) }
            : third
  const cursorOpacity = fade(frame, 510, 525) * (1 - fade(frame, 705, 720))
  const visibleCount = data.nodes.filter((node) => frame >= birth(node.order)).length
  const uiIn = fade(frame, 285, 445)
  return (
    <AbsoluteFill style={{ background: '#000', overflow: 'hidden' }}>
      <AbsoluteFill style={{
        background: 'radial-gradient(ellipse 1050px 710px at 42% 48%, #0b18223f, #000 88%)',
        opacity: fade(frame, 20, 130),
      }} />
      <svg viewBox="0 0 1920 1080" width="1920" height="1080" style={{ position: 'absolute', inset: 0 }}>
        <defs>
          <radialGradient id="nodeGlow">
            <stop stopColor="#a7ebff" stopOpacity=".48" />
            <stop offset="1" stopColor="#a7ebff" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="axis" x1="0" x2="1"><stop stopColor="#c3eaff" stopOpacity=".2" /><stop offset="1" stopColor="#80c9eb" stopOpacity=".05" /></linearGradient>
        </defs>
        <g opacity={fade(frame, 245, 405) * 0.38 * (1 - orbit.blend * 0.65)}>
          {Array.from({ length: 13 }, (_, i) => <line key={`v${i}`} x1={i * 125} y1="0" x2={i * 125} y2="925" stroke="#315265" strokeWidth="1" />)}
          {Array.from({ length: 8 }, (_, i) => <line key={`h${i}`} x1="0" y1={i * 125} x2="1495" y2={i * 125} stroke="#315265" strokeWidth="1" />)}
        </g>
        <g transform={`translate(${tx} ${ty}) scale(${scale})`}>
          <line x1={axisStart.x} x2={axisEnd.x} y1={axisStart.y} y2={axisEnd.y} stroke="url(#axis)" strokeWidth="1.2" opacity={fade(frame, 140, 330)} />
          {data.edges.map((edge, i) => {
            const start = byId.get(edge.from)
            const end = byId.get(edge.to)
            if (!start || !end) return null
            const delay = Math.max(birth(start.order), birth(end.order))
            if (frame < delay) return null
            const a = projected.get(start.id)!
            const b = projected.get(end.id)!
            const bend = (i % 2 ? -1 : 1) * Math.min(45, Math.abs(b.x - a.x) * 0.12)
            const path = `M${a.x},${a.y} Q${(a.x + b.x) / 2},${(a.y + b.y) / 2 + bend} ${b.x},${b.y}`
            const connected = activeId === edge.from || activeId === edge.to
            return <path key={i} d={path} fill="none" pathLength="100"
              stroke={edge.kind === 'quote' ? palette.violet : palette.teal}
              strokeWidth={connected ? 2.7 : edge.kind === 'quote' ? 1.7 : 1.4}
              opacity={fade(frame, delay, delay + 22) * (connected ? 0.83 : 0.30)}
              strokeDasharray="100" strokeDashoffset={100 * (1 - easeOut((frame - delay) / 30))} />
          })}
          {data.nodes.map((node) => {
            const start = birth(node.order)
            if (frame < start) return null
            const reveal = easeOut((frame - start) / (node.order < 6 ? 24 : 14))
            const point = projected.get(node.id)!
            const radius = (node.order === 0 ? 12 : Math.min(12, 4 + Math.log1p(node.likes) * 0.85)) * point.scale
            const color = nodeColor(node)
            return <g key={node.id} opacity={reveal}>
              {node.order < 6 && <circle cx={point.x} cy={point.y} r={radius * (3.2 + Math.sin(frame * .07 + node.order) * .13)} fill="url(#nodeGlow)" />}
              <circle cx={point.x} cy={point.y} r={radius * (0.55 + reveal * 0.45)} fill={color} stroke="#07131c" strokeWidth="1.6" />
              {node.order === 0 && <circle cx={point.x} cy={point.y} r={radius + 6} fill="none" stroke="#d4f5ff" opacity=".65" strokeWidth="1.6" />}
              {activeId === node.id && <circle cx={point.x} cy={point.y} r={radius + 12 + Math.sin(frame * .18) * 2} fill="none" stroke={color} strokeWidth="2.2" opacity={hoverOpacity * 0.94} />}
            </g>
          })}
        </g>
      </svg>
      <div style={{
        position: 'absolute', top: 35, left: 47, opacity: uiIn, fontSize: 30,
        fontWeight: 800, letterSpacing: '-0.07em',
      }}>sequitor<span style={{ color: palette.cyan }}>.</span></div>
      <div style={{
        position: 'absolute', top: 86, left: 48, color: '#9db7c5', fontSize: 14,
        letterSpacing: '.12em', opacity: uiIn,
      }}>CONVERSATION SPACE <span style={{ color: '#608da6', marginLeft: 15 }}>DARIO AMODEI / WE MUST PACE THE FRONTIER</span></div>
      <div style={{
        position: 'absolute', top: 37, left: 1180, color: '#a4cfdf', fontSize: 16,
        opacity: uiIn,
      }}>{visibleCount} POSTS PLACED</div>
      <div style={{
        position: 'absolute', bottom: 175, left: 46, color: '#849eaf', fontSize: 14,
        opacity: uiIn,
      }}>REFERENCE t = 0 <span style={{ marginLeft: 725 }}>+3d 1h</span><span style={{ marginLeft: 260 }}>+6d 23h</span></div>
      <div style={{
        position: 'absolute', bottom: 171, right: 453, color: '#829eaf', fontSize: 13,
        opacity: uiIn,
      }}><span style={{ color: palette.violet }}>━━━━</span> QUOTE&nbsp;&nbsp;&nbsp;&nbsp;<span style={{ color: palette.teal }}>━━━━</span> REPLY</div>
      <TimeChart frame={frame} />
      <Sidebar frame={frame} visibleCount={visibleCount} activeId={activeId} />
      {beat && <HoverPreview node={beat.node} point={screenPoint(beat.node)} opacity={hoverOpacity} />}
      <svg width="34" height="40" viewBox="0 0 34 40" style={{
        position: 'absolute', left: cursor.x + 7, top: cursor.y + 5,
        zIndex: 13, opacity: cursorOpacity, filter: 'drop-shadow(0 3px 5px #000b)',
      }}>
        <path d="M3 2v29l7-7 7 12 6-3-7-12h11Z" fill="#effaff" stroke="#0b1a24" strokeWidth="2.6" strokeLinejoin="round" />
      </svg>
      <AbsoluteFill style={{ background: '#000', opacity: 1 - fade(frame, 0, 19), pointerEvents: 'none' }} />
    </AbsoluteFill>
  )
}
