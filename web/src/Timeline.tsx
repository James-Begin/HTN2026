import { memo, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { TimelineBucket, TimelineData, TimelineSelection } from './investigation-state'
import './timeline.css'

export type { TimelineSelection } from './investigation-state'

type TimelineProps = {
  data: TimelineData | null
  selection: TimelineSelection | null
  onSelect: (selection: TimelineSelection | null) => void
}
type Period = TimelineSelection & Pick<TimelineBucket, 'count' | 'coverage'>
type Scale = 'years' | 'months'

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const formatCount = new Intl.NumberFormat('en-US')

function summarizeBuckets(buckets: TimelineBucket[]) {
  // A later entry replaces an earlier entry for the same month; it is not
  // another contribution to the total.
  const supplied = new Map<number, Map<number, TimelineBucket>>()
  for (const bucket of buckets) {
    const months = supplied.get(bucket.year) ?? new Map<number, TimelineBucket>()
    months.set(bucket.month, bucket)
    supplied.set(bucket.year, months)
  }

  const months: TimelineBucket[] = []
  const years: Period[] = [...supplied.keys()].sort((a, b) => a - b).map(year => {
    const yearMonths = MONTH_NAMES.map((_, index): TimelineBucket =>
      supplied.get(year)!.get(index + 1) ?? {
        year, month: index + 1, count: null, coverage: 'unavailable',
      },
    )
    months.push(...yearMonths)
    const known = yearMonths.filter(month => month.count !== null && month.coverage !== 'unavailable')
    return {
      year,
      count: known.length ? known.reduce((total, month) => total + month.count!, 0) : null,
      coverage: !known.length ? 'unavailable'
        : yearMonths.every(month => month.count !== null && month.coverage === 'complete')
          ? 'complete' : 'partial',
    }
  })
  return { months, years }
}

function periodLabel(period: TimelineSelection) {
  return period.month ? `${MONTH_NAMES[period.month - 1]} ${period.year}` : String(period.year)
}

function samePeriod(left: TimelineSelection | null, right: TimelineSelection) {
  return left?.year === right.year && left?.month === right.month
}

function countLabel(period: Period) {
  return period.count === null || period.coverage === 'unavailable' ? '—' : formatCount.format(period.count)
}

function TimelineView({ data, selection, onSelect }: TimelineProps & { data: TimelineData }) {
  const series = useMemo(() => summarizeBuckets(data.buckets), [data.buckets])
  const firstYear = series.years[0].year
  const lastYear = series.years[series.years.length - 1].year
  const preferredYear = series.years.some(year => year.year === data.preferredPeriod?.year)
    ? data.preferredPeriod!.year : lastYear
  const [scale, setScale] = useState<Scale>('months')
  const [requestedYear, setViewedYear] = useState(preferredYear)
  const viewedYear = series.years.some(year => year.year === requestedYear) ? requestedYear : preferredYear
  const [hovered, setHovered] = useState<TimelineSelection | null>(null)
  const [focused, setFocused] = useState<TimelineSelection | null>(null)
  const rowsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (requestedYear !== viewedYear) {
      setViewedYear(viewedYear)
      setHovered(null)
      setFocused(null)
    }
  }, [requestedYear, viewedYear])

  const rows = scale === 'months'
    ? series.months.filter(month => month.year === viewedYear)
    : [...series.years].reverse()
  const selectedRow = rows.find(row => samePeriod(selection, row))
  const fallback = scale === 'months'
    ? rows.find(row => row.month === data.preferredPeriod?.month) ?? rows[rows.length - 1]
    : rows.find(row => row.year === viewedYear) ?? rows[0]
  // Preview state stores identities only. Always resolve counts and coverage
  // from the latest data, and ignore periods no longer present in this view.
  const readout = rows.find(row => samePeriod(hovered, row))
    ?? rows.find(row => samePeriod(focused, row)) ?? selectedRow ?? fallback
  const maximum = Math.max(1, ...rows.map(row => row.coverage === 'unavailable' ? 0 : row.count ?? 0))
  const provenance = data.provenance === 'sample' ? 'saved-post' : data.provenance
  const readoutCaption = readout.count === null || readout.coverage === 'unavailable'
    ? (data.provenance === 'sample' ? 'no coverage for this period' : `${provenance} count unavailable`)
    : data.provenance === 'sample' ? 'saved posts · selected sample' : `${readout.coverage === 'partial' ? 'partial ' : ''}${provenance} count`
  const yearIndex = series.years.findIndex(year => year.year === viewedYear)

  function resetPreview() {
    setHovered(null)
    setFocused(null)
  }

  function changeScale(nextScale: Scale) {
    resetPreview()
    setScale(nextScale)
  }

  function navigateYear(direction: number) {
    const year = series.years[yearIndex + direction]
    if (!year) return
    resetPreview()
    setViewedYear(year.year)
  }

  function moveFocus(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number
    switch (event.key) {
      case 'ArrowUp': next = Math.max(0, index - 1); break
      case 'ArrowDown': next = Math.min(rows.length - 1, index + 1); break
      case 'Home': next = 0; break
      case 'End': next = rows.length - 1; break
      default: return
    }
    event.preventDefault()
    setHovered(null)
    rowsRef.current?.querySelectorAll<HTMLButtonElement>('.tl-row')[next]?.focus()
  }

  return (
    <>
      <header className="tl-heading">
        <h2 className="tl-title">Timeline</h2>
        <p className="tl-subtitle" title={data.query}>{data.provenance === 'sample' ? 'Saved-post counts' : provenance === 'illustrative' ? 'Illustrative counts' : 'Measured counts'}</p>
      </header>

      <div className="tl-scale" role="group" aria-label="Timeline scale">
        {(['years', 'months'] as const).map(option => (
          <button
            key={option}
            type="button"
            className="tl-scale-button"
            aria-pressed={scale === option}
            onClick={() => changeScale(option)}
          >
            {option === 'years' ? 'Years' : 'Months'}
          </button>
        ))}
      </div>

      <div className="tl-period-nav">
        {scale === 'months' ? (
          <>
            <button
              type="button"
              className="tl-arrow"
              aria-label="Previous year"
              disabled={viewedYear === firstYear}
              onClick={() => navigateYear(-1)}
            ><span aria-hidden="true">←</span></button>
            <span className="tl-viewed-year">{viewedYear}</span>
            <button
              type="button"
              className="tl-arrow"
              aria-label="Next year"
              disabled={viewedYear === lastYear}
              onClick={() => navigateYear(1)}
            ><span aria-hidden="true">→</span></button>
          </>
        ) : (
          <>
            <span className="tl-range">{firstYear}–{lastYear}</span>
            <button
              type="button"
              className="tl-explore"
              aria-label={`Explore months in ${viewedYear}`}
              onClick={() => changeScale('months')}
            >Explore months <span aria-hidden="true">→</span></button>
          </>
        )}
      </div>

      <div className="tl-readout" aria-live="polite" aria-atomic="true">
        <span className="tl-readout-date">{periodLabel(readout)}</span>
        <strong className="tl-readout-count">{countLabel(readout)}</strong>
        <span className="tl-readout-caption">{readoutCaption}</span>
      </div>

      <div
        key={scale === 'months' ? `months-${viewedYear}` : 'years'}
        className="tl-rows"
        ref={rowsRef}
        role="group"
        aria-label={scale === 'months' ? `Monthly ${provenance} counts for ${viewedYear}` : `Yearly ${provenance} counts, newest first`}
        onMouseLeave={() => setHovered(null)}
        onBlur={event => {
          if (!event.currentTarget.contains(event.relatedTarget)) setFocused(null)
        }}
      >
        {rows.map((row, index) => (
          <button
            key={`${row.year}-${row.month ?? 'year'}`}
            type="button"
            className={`tl-row${samePeriod(readout, row) ? ' tl-row-preview' : ''}${row.count === null || row.coverage === 'unavailable' ? ' tl-row-unavailable' : ''}`}
            aria-label={`${periodLabel(row)}: ${countLabel(row)} ${row.count === null ? 'unavailable' : row.coverage} ${provenance} count. Focus dated observations.`}
            aria-pressed={samePeriod(selection, row)}
            onMouseEnter={() => setHovered({ year: row.year, month: row.month })}
            onFocus={() => { setHovered(null); setFocused({ year: row.year, month: row.month }) }}
            onKeyDown={event => moveFocus(event, index)}
            onClick={() => {
              onSelect(row.month ? { year: row.year, month: row.month } : { year: row.year })
              if (scale === 'years') {
                resetPreview()
                setViewedYear(row.year)
              }
            }}
          >
            <span className="tl-row-label">{row.month ? MONTH_NAMES[row.month - 1].slice(0, 3) : row.year}</span>
            <span className="tl-bar-track" aria-hidden="true">
              <span className="tl-bar" style={{ width: `${row.coverage === 'unavailable' ? 0 : (row.count ?? 0) / maximum * 100}%` }} />
            </span>
            <span className="tl-row-count">
              {countLabel(row)}
              {row.count !== null && row.coverage === 'partial' && <span className="tl-count-coverage">partial</span>}
            </span>
          </button>
        ))}
      </div>

      <div className="tl-filter">
        {selection ? (
          <>
            <span className="tl-filter-label">Focus: {periodLabel(selection)}</span>
            <button type="button" className="tl-clear" onClick={() => onSelect(null)}>Clear focus</button>
          </>
        ) : <span className="tl-hint">Select a period to focus the trail.</span>}
      </div>
      <p className="tl-footer">
        {data.provenance === 'sample' ? 'Selected saved posts, not total X activity. — means no coverage, not zero.' : <>
          {data.provenance === 'illustrative' ? 'Demo series, not API measurements.' : 'Measured activity counts.'}
          {series.months.some(month => month.count === null || month.coverage !== 'complete') && ' — means unavailable. Partial counts include only known activity.'}
        </>}
      </p>
    </>
  )
}

const Timeline = memo(function Timeline({ data, ...props }: TimelineProps) {
  return (
    <section id="trace-timeline" className="timeline-space" aria-label="Activity timeline">
      {data && data.buckets.length ? <TimelineView data={data} {...props} /> : (
        <header className="tl-heading">
          <h2 className="tl-title">Timeline</h2>
          <p className="tl-subtitle" role="status">Waiting for activity data</p>
        </header>
      )}
    </section>
  )
})

export default Timeline
