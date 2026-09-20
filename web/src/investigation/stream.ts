import type { Bucket, Post, Run, StreamEvent } from './types'

export function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function isInputPost(post: Post) {
  return post.sourceType === 'input' || post.id === 'seed-text' || post.author === 'Seed text' || post.author === 'Search input'
}

export function normalizePost(post: Post): Post {
  return isInputPost(post)
    ? { ...post, sourceType: 'input', author: 'Search input', publishedAt: '', url: undefined }
    : { ...post }
}

export function mergePosts(existing: Post[], incoming: Post[]): Post[] {
  const positions = new Map(existing.map((post, index) => [post.id, index]))
  const merged = [...existing]
  for (const value of incoming) {
    const post = normalizePost(value)
    const index = positions.get(post.id)
    if (index === undefined) {
      positions.set(post.id, merged.length)
      merged.push(post)
    } else {
      const prior = merged[index]
      merged[index] = normalizePost({ ...prior, ...post,
        textIsExcerpt: prior.text === post.text && prior.textIsExcerpt ? true : post.textIsExcerpt })
    }
  }
  return merged
}

export function mergeBucket(existing: Bucket[], incoming: Bucket): Bucket[] {
  return [...new Map([...existing, incoming].map(bucket => [bucket.day, bucket])).values()]
    .sort((a, b) => a.day.localeCompare(b.day))
}

function validPost(value: unknown): value is Post {
  return record(value) && ['id', 'text', 'publishedAt', 'author'].every(key => typeof value[key] === 'string')
    && ['handle', 'avatar', 'url', 'scope', 'captureTime', 'basetenKind', 'rankingMethod', 'spaceMethod', 'parentId', 'quotedPostId'].every(key => value[key] == null || typeof value[key] === 'string')
    && ['likes', 'reposts', 'replies', 'followers', 'rankingScore', 'sameClaimScore', 'semanticScore', 'lexicalScore', 'spaceScore', 'spaceY', 'spaceZ', 'spaceDirectionQuality'].every(key => value[key] == null || typeof value[key] === 'number' && Number.isFinite(value[key]))
}

export function validBucket(value: unknown): value is Bucket {
  return record(value) && typeof value.day === 'string' && !Number.isNaN(Date.parse(value.day))
    && (value.count === null || typeof value.count === 'number' && Number.isFinite(value.count) && value.count >= 0)
    && ['complete', 'partial', 'sample', 'unavailable'].includes(String(value.coverage))
}

function validPlan(value: unknown) {
  return value === null || record(value)
    && ['contextLabel', 'volumePhrase', 'volumeFallback', 'discoveryPhrase', 'expansionReason', 'whyDiscovery', 'model', 'error'].every(key => value[key] == null || typeof value[key] === 'string')
    && ['entities', 'angles', 'uncertainties', 'discoveryQueries', 'anchorQueries', 'expansionQueries'].every(key => value[key] == null || Array.isArray(value[key]) && value[key].every(item => typeof item === 'string'))
}

function validCuration(value: unknown): boolean {
  return value == null || typeof value === 'string' || record(value)
    && ['status', 'model'].every(key => value[key] == null || typeof value[key] === 'string')
}

function validModel(value: unknown): boolean {
  return value == null || record(value) && (value.openai == null || typeof value.openai === 'string') && validCuration(value.baseten)
}

export function validateEvent(message: StreamEvent) {
  const payload = message.payload
  let valid = true
  if (message.type === 'run.ready') valid = ['id', 'seed', 'title', 'scope', 'selectedDay', 'rankingCoverage', 'note'].every(key => typeof payload[key] === 'string')
    && ['live', 'saved'].includes(String(payload.kind)) && Array.isArray(payload.posts) && payload.posts.every(validPost)
    && Array.isArray(payload.buckets) && payload.buckets.every(validBucket) && (payload.seedPost == null || validPost(payload.seedPost))
    && (payload.searchPlan == null || validPlan(payload.searchPlan)) && validModel(payload.model)
  if (message.type === 'model.ready') valid = validCuration(payload.model)
  if (message.type === 'run.completed') valid = validModel(payload.model)
  if (payload.xSpend != null) valid = valid && typeof payload.xSpend === 'number' && Number.isFinite(payload.xSpend)
  if (message.type === 'posts.upsert') valid = Array.isArray(payload.posts) && payload.posts.every(validPost)
  if (message.type === 'buckets.upsert') valid = validBucket(payload.bucket)
  if (message.type === 'seed.resolved') valid = typeof payload.text === 'string' && (payload.post == null || validPost(payload.post))
  if (message.type === 'plan.ready' || message.type === 'context.expanded') valid = validPlan(payload.plan)
  if (message.type === 'stage') valid = typeof payload.name === 'string'
  if (message.type === 'run.started') valid = typeof payload.seed === 'string'
  if (!valid) throw new Error('Invalid investigation event received; partial results retained')
}

export function normalizeRun(run: Run): Run {
  return {
    ...run,
    posts: run.posts.map(normalizePost),
    seedPost: run.seedPost ? normalizePost(run.seedPost) : undefined,
    savedPeriods: run.savedPeriods ? Object.fromEntries(Object.entries(run.savedPeriods).map(([day, period]) =>
      [day, { ...period, posts: period.posts.map(normalizePost) }])) : undefined,
  }
}
