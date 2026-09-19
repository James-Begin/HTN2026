import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowRight, ArrowUpRight, AudioLines, Check, CircleHelp, Command,
  Copy, CornerDownLeft, Fingerprint, GitBranch, Globe2, Hexagon,
  Info, Layers3, Link2, Plus, Radio, Search, ShieldCheck, Terminal,
} from 'lucide-react'
import { demos } from './demo'
import { frontierRecording } from './frontier-recording'
import type { Demo } from './demo'
import type { InvestigationState } from './investigation-state'
import PreviewInvestigation from './PreviewInvestigation'
import Dialog from './Dialog'

const examples = [frontierRecording, ...demos.filter(demo => demo.id !== 'frontier')]
const CLI_COMMAND = 'python cli.py "your claim here" --json'
type DialogKind = 'method' | 'cli' | null

function Mark() {
  return <span className="brand-mark" aria-hidden="true"><Hexagon /><span /><span /><span /></span>
}

function ModeIcon({ mode }: { mode: Demo['mode'] }) {
  return mode === 'lineage' ? <GitBranch size={17} /> : mode === 'verify' ? <AudioLines size={17} /> : <Fingerprint size={17} />
}

function HeroTrace() {
  return <div className="hero-trace" role="img" aria-label="Illustration: following a claim backward through time">
    <div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit orbit-three" />
    <div className="trace-dots" />
    <svg className="hero-paths" viewBox="0 0 430 330" fill="none" aria-hidden="true">
      <path className="path-faint" d="M45 92H140C165 92 165 157 193 157H320M78 255H146C174 255 166 157 193 157M320 157H353V71" />
      <path className="path-active" d="M320 157H193C165 157 165 92 140 92H45" />
      <circle cx="194" cy="157" r="5" fill="var(--mint)" />
      <circle cx="353" cy="71" r="3" fill="var(--muted)" />
    </svg>
    <div className="floating-source original"><span className="floating-label"><Fingerprint size={12} /> AN EARLIER MATCH</span><div>A phrase before<br />the headline.</div><span className="mini-date">Follow the wording back <ArrowUpRight size={12} /></span></div>
    <div className="floating-source current"><span className="floating-label"><Radio size={12} /> THE CLAIM</span><div>“We must pace<br />the frontier.”</div><div className="source-lines"><i /><i /><i /></div></div>
    <div className="floating-tag"><Layers3 size={13} /><span>Same words. Different context.</span></div>
    <span className="visual-footnote">A TRAIL, NOT A TRUTH SCORE</span>
  </div>
}

function CaseCard({ demo, onSelect }: { demo: Demo; onSelect: (demo: Demo) => void }) {
  return <button className={`case-card case-${demo.mode}`} onClick={() => onSelect(demo)}>
    <div className="case-top"><span className="case-mode"><ModeIcon mode={demo.mode} />{demo.mode === 'lineage' ? 'TRACE HISTORY' : demo.mode === 'verify' ? 'CHECK CORROBORATION' : 'RESOLVE A POST'}</span><span className="case-number">/{demo.number}</span></div>
    <h3>{demo.title.split('\n').map((line, i) => <span key={line}>{i > 0 && <br />}{line}</span>)}</h3>
    <p>{demo.subtitle}</p>
    <div className="case-footer"><span>{demo.sourceType === 'snapshot' ? 'Replay saved X sources' : 'Explore simulated example'}</span><ArrowUpRight size={17} /></div>
  </button>
}

export default function App() {
  const [view, setView] = useState<'explore' | 'investigation'>('explore')
  const [selected, setSelected] = useState<Demo>(examples[0])
  const [run, setRun] = useState(0)
  const [input, setInput] = useState('')
  const [inputNote, setInputNote] = useState('')
  const [dialog, setDialog] = useState<DialogKind>(null)
  const [copied, setCopied] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && !document.querySelector('dialog[open]')) {
        event.preventDefault(); setView('explore')
        window.setTimeout(() => inputRef.current?.focus(), 0)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  function start(demo: Demo) {
    setSelected(demo); setRun(value => value + 1); setView('investigation')
    setInput(demo.claim); setInputNote('')
    window.scrollTo({ top: 0, behavior: 'instant' })
  }

  function goHome() {
    setView('explore')
    window.scrollTo({ top: 0, behavior: 'instant' })
  }

  function newInvestigation() {
    goHome(); setInput(''); setInputNote('')
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const text = input.trim()
    const demo = text ? examples.find(item => [item.claim, ...(item.inputAliases ?? [])].some(value => value.toLowerCase() === text.toLowerCase())) : examples[0]
    if (demo) start(demo)
    else setInputNote('Live search isn’t connected yet. Your text hasn’t been sent anywhere. Choose an example below to explore the interface.')
  }

  function scrollCases() {
    goHome()
    window.setTimeout(() => document.getElementById('case-library')?.scrollIntoView({ block: 'start' }), 0)
  }

  async function copyCommand() {
    try { await navigator.clipboard.writeText(CLI_COMMAND); setCopied(true) }
    catch { setCopied(false) }
  }

  function exportExample(state: InvestigationState) {
    const data = {
      kind: 'investigation-state-snapshot', simulated: state.provenance === 'preview',
      playbackTiming: 'illustrative', modelRun: false,
      provenance: state.recording?.files ?? ['demo/cases.jsonl', 'eval/pairs.jsonl', 'tests/fixtures/corpus.json', 'README.md'],
      state,
      warning: state.recording
        ? 'Saved X source payloads with editorial annotations, not a recorded pipeline execution. Counts cover only the selected saved posts. Only state derived from received replay events is included.'
        : 'Only state derived from received events is included. This preview is not a captured event stream or current API result. Timeline volumes are illustrative design fixtures, not measurements. No live investigation was run.',
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `claimtrace-${state.recording ? 'snapshot' : 'demo'}-${selected.id}.json`; link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="topbar">
      <button className="brand" onClick={goHome} aria-label="Claimtrace home"><Mark /><span>claimtrace<span className="brand-period">.</span></span></button>
      <nav className="top-navigation" aria-label="Main navigation">
        <button className="new-investigation" onClick={newInvestigation} aria-label="New investigation"><Plus size={15} /><span>New investigation</span></button>
        <button className="examples-navigation" onClick={scrollCases}>Examples</button>
        <button onClick={() => { setCopied(false); setDialog('cli') }} aria-label="Open CLI commands" title="CLI commands"><Terminal size={17} /><span className="nav-cli-label">CLI</span></button>
        <button className="icon-button" onClick={() => setDialog('method')} aria-label="About this preview"><CircleHelp size={17} /></button>
      </nav>
    </header>
    <main id="main">
      {view === 'explore' ? <div className="overview page-enter">
        <section className="hero"><div className="hero-copy"><div className="eyebrow hero-eyebrow"><span />FOLLOW THE EVIDENCE. NOT THE NOISE.</div><h1>Every claim has<br />a <em>backstory.</em><span className="heading-asterisk">✳</span></h1><p>Go beyond the post. Trace where a claim appeared,<br className="desktop-break" /> how it spread, and what the evidence actually says.</p><div className="hero-principle"><ShieldCheck size={15} />No truth scores. Just a clearer picture.</div></div><HeroTrace /></section>
        <section className="input-section" aria-label="Start an investigation">
          <form className={`claim-input ${inputNote ? 'has-note' : ''}`} onSubmit={submit}>
            <div className="input-label"><label htmlFor="claim"><Link2 size={15} />START WITH A CLAIM</label><span>Text or an X post URL</span></div>
            <textarea ref={inputRef} id="claim" value={input} onChange={event => { setInput(event.target.value); setInputNote('') }} placeholder="Something doesn’t add up? Paste it here." rows={2} onKeyDown={event => { if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} />
            <div className="input-bottom"><span className="input-mode"><Globe2 size={14} />X archive<span className="tiny-divider" /><span className="muted">Offline examples</span></span><button className="primary-button" type="submit">{input.trim() ? 'Preview investigation' : 'Explore an example'}<ArrowRight size={17} /></button></div>
          </form>
          {inputNote ? <p className="input-note" role="status"><Info size={15} />{inputNote}</p> : <div className="input-footnote"><span><ShieldCheck size={12} />Nothing is sent to an API in this preview.</span><span><Command size={11} /><CornerDownLeft size={11} /> to explore</span></div>}
        </section>
        <section id="case-library" className="library"><div className="section-heading"><div><span className="eyebrow">A FEW THREADS WORTH PULLING</span><h2>Start with a story.</h2></div><span className="section-aside">Offline examples <span>↙</span></span></div><div className="case-grid">{examples.map(demo => <CaseCard key={demo.id} demo={demo} onSelect={start} />)}</div><p className="library-note"><Info size={12} />A saved X source snapshot and simulated examples. No live investigation required.</p></section>
        <footer className="page-footer"><span>LESS ASSUMPTION. MORE CONTEXT.</span><button onClick={() => setDialog('method')}>A look under the hood <ArrowUpRight size={13} /></button></footer>
      </div> : <PreviewInvestigation key={`${selected.id}-${run}`} runId={`${selected.sourceType === 'snapshot' ? 'snapshot' : 'preview'}:${selected.id}:${run}`} demo={selected} onBack={goHome} onExport={exportExample} onAbout={() => setDialog('method')} />}
    </main>
    {dialog === 'method' && <Dialog title="Evidence, with its limits intact." onClose={() => setDialog(null)}>
      <p className="modal-intro">Claimtrace investigates where a claim appears and how people repeat it. It doesn’t assign a truth score.</p>
      <div className="method-list"><div><Search size={21} /><div><h3>Explore the timeline.</h3><p>Hover or focus a month or year to see its count. Select a period to highlight dated observations. Unknown dates remain visible, never guessed.</p></div></div><div><GitBranch size={21} /><div><h3>Follow the lineage.</h3><p>Earlier wording, an announcement, and a reaction are different things. Chronology alone does not establish who copied whom.</p></div></div><div><ShieldCheck size={21} /><div><h3>Go straight to the source.</h3><p>Posts with saved IDs link directly to X. Other fixtures offer a clearly labelled text search, not an invented permalink.</p></div></div></div>
      <div className="modal-notice"><Info size={17} /><p><strong>Offline examples.</strong> The frontier story uses captured X posts with editorial notes; its timeline counts only the selected saved sources. Other examples use illustrative counts and hand-labelled fixtures. All playback timing is prepared for the demo; there is no live retrieval or inference.</p></div>
    </Dialog>}
    {dialog === 'cli' && <Dialog title="Your terminal. The same trail." onClose={() => setDialog(null)}>
      <p className="modal-intro">Claimtrace already has a Python CLI. Run it from the project directory to trace a claim, or stream its events as newline-delimited JSON.</p>
      <div className="terminal-window"><div className="terminal-title"><span /><span /><span /><span>claimtrace — terminal</span></div><pre><span className="terminal-comment"># An investigation, without the browser</span>{'\n'}<span className="terminal-prompt">$ </span>python cli.py "your claim here"{'\n\n'}<span className="terminal-comment"># The same events, ready for your tools</span>{'\n'}<span className="terminal-prompt">$ </span>{CLI_COMMAND}</pre></div>
      <button className="secondary-button copy-command" onClick={copyCommand}>{copied ? <Check size={15} /> : <Copy size={15} />}{copied ? 'Copied to clipboard' : 'Copy JSON command'}</button><p className="modal-small">Live CLI runs require X and Baseten credentials and may incur API charges. The web preview does not invoke the CLI.</p>
    </Dialog>}
  </div>
}
