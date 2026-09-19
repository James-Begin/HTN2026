// Curated UI examples, not captured event streams or current API responses.
// Measurements: ../demo/cases.jsonl and ../README.md.
// Text and hand labels: ../eval/pairs.jsonl.
// Playback timing and archive-window animation are deliberately illustrative.
import type { Evidence, Mode, TraceMoment, Verdict } from './investigation-state'
type DemoEvidence = Evidence & { verdict: Verdict; explanation: string }
export type Demo = {
  sourceType?: 'illustrative' | 'snapshot'
  inputAliases?: string[]
  id: string
  number: string
  mode: Mode
  title: string
  subtitle: string
  claim: string
  anchor: string
  headline: string
  takeaway: string
  summary: string
  caveat: string
  evidence: DemoEvidence[]
}

export const demos: Demo[] = [
  {
    id: 'frontier', number: '01', mode: 'lineage',
    title: 'Before the essay,\nthere was a phrase.',
    subtitle: 'An older phrase is not necessarily the origin of a claim.',
    claim: "We Must Pace the Frontier: I've written a new essay on why the AI industry should slow down, with a three-part plan",
    anchor: 'pace the frontier',
    headline: 'The phrase came first. Not the claim.',
    takeaway: 'An earlier match is not an origin.',
    summary: 'The documented search found this phrase in an August post, before the September activity peak. But the earlier post uses it as a slogan—not as an announcement of the essay. Shared wording alone does not establish where the claim began.',
    caveat: 'This is a documented historical example, not a fresh search. The archive animation and playback timing are illustrative. The earliest lexical match is not a verified origin.',
    evidence: [
      {
        id: 'ptf-08', author: 'Earlier phrase match', context: '12 AUG 2026 · ARCHIVE RESULT',
        text: '“ceterum censeo we must pace the frontier of global machine intelligence progress”',
        verdict: 'uncertain',
        explanation: 'The wording overlaps, but this is a slogan rather than an essay announcement. The evaluation fixture marks this label as debatable.',
        url: 'https://x.com/i/status/2087370436959186977',
        publishedAt: '2026-08-12T02:47:48Z',
        likes: 247,
      },
      {
        id: 'ptf-02', author: 'Title and link', context: 'EVALUATION EXAMPLE',
        text: 'We Must Pace the Frontier https://t.co/sezx1DnTZn', verdict: 'same',
        explanation: 'The hand-labelled fixture treats the title and a link to the essay as the same assertion. This is a fixture label, not a new model prediction.',
      },
      {
        id: 'ptf-05', author: 'Reaction to the essay', context: 'EVALUATION EXAMPLE',
        text: "Elon, perhaps the last person I would've thought would agreed that we must pace the frontier", verdict: 'meta',
        explanation: 'Commentary about a reaction is not a restatement of the announcement. The fixture labels it meta; this is not independent corroboration.',
      },
    ],
  },
  {
    id: 'ssi', number: '02', mode: 'verify',
    title: 'A lot of repetition.\nHow much reporting?',
    subtitle: 'Separate amplification from people making the same assertion.',
    claim: 'ssi are delayed after a catastrophic security incident discovered after seeing what happened with openai, order of magnitude more damage caused.',
    anchor: 'catastrophic security incident',
    headline: 'Mostly repetition. Not independent reporting.',
    takeaway: 'Amplification is not corroboration.',
    summary: 'In the documented example, 47 matching posts included only one non-retweet. That describes amplification within the query results—not 47 independent sources. A denial and a question about the source also mention the claim without asserting it.',
    caveat: 'Counts are from demo/cases.jsonl and describe a historical seven-day window. The semantic examples use hand labels from eval/pairs.jsonl; they do not filter the aggregate counts.',
    evidence: [
      {
        id: 'ssi-03', author: 'A paraphrased assertion', context: 'EVALUATION EXAMPLE',
        text: 'Safe Superintelligence has pushed back its timeline following a serious breach', verdict: 'same',
        explanation: 'A hand-labelled same-claim paraphrase. Repeating an assertion does not establish its truth or the independence of the source.',
      },
      {
        id: 'ssi-10', author: 'A denial, not support', context: 'EVALUATION EXAMPLE',
        text: '@TheNeuralLair @iruletheworldmo No public reports confirm any security incident at SSI', verdict: 'meta',
        explanation: 'The post disputes the claim. Topic relevance alone could mistake this for support; the hand-labelled fixture correctly separates it as meta.',
      },
      {
        id: 'ssi-05', author: 'Same acronym, different subject', context: 'EVALUATION EXAMPLE',
        publishedAt: '2017',
        text: 'Penalties for SSI are delayed about 12-18 months, but can cost you thousands', verdict: 'different',
        explanation: 'SSI refers to Supplemental Security Income here, not Safe Superintelligence. This is an incidental keyword collision in the hand-labelled evaluation.',
      },
    ],
  },
  {
    id: 'covfefe', number: '03', mode: 'resolve',
    title: 'The post is gone.\nThe timestamp isn’t.',
    subtitle: 'A deleted post and a surviving follow-up tell different stories.',
    claim: 'https://x.com/realDonaldTrump/status/869766994899468288',
    anchor: 'covfefe',
    headline: 'Gone from the feed. Not without a trace.',
    takeaway: 'A surviving reply is not the original.',
    summary: 'The documented resolver response identifies a deleted post. Its Snowflake ID decodes to May 31, 2017 at 04:06:25.730 UTC. A live follow-up discusses the same phrase, but it is not the original. Decoding the ID recovers a timestamp—not the missing text.',
    caveat: 'The deleted state comes from a documented endpoint response, not a live check. The ID-derived timestamp alone does not prove that a post existed. Example text comes from evaluation fixtures.',
    evidence: [
      {
        id: 'cov-01', author: 'Text preserved in a retweet', context: 'EVALUATION EXAMPLE',
        text: 'RT @Lowenaffchen: Despite the constant negative press covfefe', verdict: 'same',
        explanation: 'This fixture preserves the wording in a retweet. The resolver itself cannot recover the deleted text.',
      },
      {
        id: 'cov-02', author: 'The surviving follow-up', context: 'A DIFFERENT POST',
        text: 'Who can figure out the true meaning of "covfefe" ??? Enjoy!', verdict: 'meta',
        explanation: 'A follow-up about the phrase, not the missing original. Keyword retrieval can surface this post without establishing the distinction.',
        url: 'https://x.com/i/status/869858333477523458',
        publishedAt: '2017-05-31T10:09:22Z',
      },
    ],
  },
]

// Only dates explicitly recorded in the project are assigned. Undated fixtures
// stay undated; their order below is explanatory, not an inferred chronology.
export const traceMoments: Record<string, TraceMoment[]> = {
  frontier: [
    { id: 'first', date: '2026-08-12T02:47:48Z', title: 'An earlier phrase surfaces.', description: 'The wording appears as a slogan before the essay’s activity peak. An earlier match, but not the same announcement.', evidenceId: 'ptf-08', label: 'Earliest phrase match' },
    { id: 'peak', date: '2026-09-12', title: 'The conversation gets louder.', description: 'The documented example reaches its activity peak. Attention tells us when a phrase spreads—not where its claim began.', label: 'Documented activity peak' },
    { id: 'title', title: 'A title carries the assertion.', description: 'The title and a link to the essay refer to the announcement. The exact publication date was not saved in this fixture.', evidenceId: 'ptf-02' },
    { id: 'reaction', title: 'A reaction is not a restatement.', description: 'A post about who agreed with the essay is commentary, not another report of the announcement.', evidenceId: 'ptf-05' },
  ],
  ssi: [
    { id: 'collision', date: '2017', title: 'The acronym has another life.', description: 'An older match refers to Supplemental Security Income. Shared letters point to a different subject.', evidenceId: 'ssi-05', label: 'Keyword collision' },
    { id: 'assertion', title: 'The assertion is repeated.', description: 'Different wording can make the same assertion. It does not establish an independent source.', evidenceId: 'ssi-03' },
    { id: 'denial', title: 'Not every mention is support.', description: 'This reply disputes the claim. Counting it as corroboration would reverse its meaning.', evidenceId: 'ssi-10' },
  ],
  covfefe: [
    { id: 'deleted', date: '2017-05-31T04:06:25.730Z', title: 'The original is unavailable.', description: 'A documented deletion response, paired with a timestamp decoded from the post ID. The ID does not recover the text.', url: 'https://x.com/i/status/869766994899468288', label: 'Deleted original' },
    { id: 'followup', date: '2017-05-31T10:09:22Z', title: 'A follow-up survives.', description: 'The surviving post talks about the phrase. It is not the original, even when search places it nearby.', evidenceId: 'cov-02' },
    { id: 'retweet', title: 'The wording survives elsewhere.', description: 'An evaluation example preserves the text inside a retweet. Its own timestamp and post ID were not saved.', evidenceId: 'cov-01' },
  ],
}
