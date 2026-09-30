import { Easing, interpolate } from 'remotion'

export const clamp01 = (value: number) => Math.min(1, Math.max(0, value))
export const easeOut = (value: number) => 1 - Math.pow(1 - clamp01(value), 3)
export const easeInOut = (value: number) => {
  const t = clamp01(value)
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}
export const fade = (frame: number, start: number, end: number) =>
  interpolate(frame, [start, end], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.22, 1, 0.36, 1) })

export const palette = {
  black: '#020508',
  panel: '#0b1118',
  border: '#284455',
  text: '#eef7fb',
  muted: '#91a8b6',
  cyan: '#94d8f3',
  teal: '#7ee3dc',
  violet: '#bfa9ff',
}
