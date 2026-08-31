import { useMemo, useState } from 'react';

import type { Segment, SegmentList } from '@/api/types';
import { ErrorAlert } from '@/components/ErrorAlert';
import { SegmentEditor } from '@/features/segments/SegmentEditor';
import type { TranslationKey } from '@/i18n/en';
import { useT } from '@/i18n/LocaleProvider';
import { describeFlag, formatDeviation, formatTimestamp } from '@/lib/format';

/**
 * Which segments to show.
 *
 * A finished dub of a long video runs to several hundred rows, and review is the task of
 * finding the few that need attention. Scrolling all of them to spot nine flagged ones is
 * the difference between a usable review pass and an unusable one.
 */
const FILTERS: readonly { id: string; label: TranslationKey; matches: (s: Segment) => boolean }[] =
  [
    { id: 'all', label: 'segments.filterAll', matches: () => true },
    { id: 'flagged', label: 'segments.filterFlagged', matches: (s) => s.flags.length > 0 },
    {
      id: 'unapproved',
      label: 'segments.filterUnapproved',
      matches: (s) => s.review_state !== 'approved',
    },
    { id: 'failed', label: 'segments.filterFailed', matches: (s) => s.status === 'failed' },
  ];

/** Timeline-oriented segment list and keyboard-accessible correction editor. */
export function SegmentWorkspace({
  projectId,
  data,
  loading,
  error,
}: {
  projectId: string;
  data: SegmentList | undefined;
  loading: boolean;
  error: unknown;
}) {
  const t = useT();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filterId, setFilterId] = useState('all');

  const active = FILTERS.find((filter) => filter.id === filterId) ?? FILTERS[0];
  const segments = data?.segments;
  const visible = useMemo(
    () => (segments ?? []).filter((segment) => active?.matches(segment) ?? true),
    [segments, active],
  );

  if (loading) return <section className="card muted">{t('segments.loading')}</section>;
  if (error) return <ErrorAlert error={error} />;
  if (!data || data.segments.length === 0) return null;

  // Keep the editor on a row that is still on screen after the filter changes.
  const selected = visible.find((segment) => segment.id === selectedId) ?? visible[0];

  return (
    <section className="stack" aria-labelledby="segments-heading">
      <div className="card segment-summary">
        <div>
          <h2 id="segments-heading">{t('segments.title')}</h2>
          <p className="muted small">{t('segments.subtitle')}</p>
        </div>
        <div className="row small">
          <span>{t('segments.total', { count: data.summary.total })}</span>
          <span>{t('segments.approved', { count: data.summary.approved })}</span>
          <span className={data.summary.flagged ? 'badge badge--warn' : 'badge'}>
            {t('segments.flagged', { count: data.summary.flagged })}
          </span>
          <span className={data.summary.failed ? 'badge badge--danger' : 'badge'}>
            {t('segments.failed', { count: data.summary.failed })}
          </span>
        </div>
      </div>

      <div className="card row segment-filters">
        <div className="filters" role="group" aria-label={t('segments.filterLabel')}>
          {FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              aria-pressed={filter.id === active?.id}
              onClick={() => {
                setFilterId(filter.id);
              }}
            >
              {t(filter.label)}
            </button>
          ))}
        </div>
        <span className="topbar__spacer" />
        <span className="muted small">
          {t('segments.showingCount', { shown: visible.length, total: data.segments.length })}
        </span>
      </div>
      <div className="split">
        <div className="card table-scroll">
          <table className="segments">
            <thead>
              <tr>
                <th>{t('segments.time')}</th>
                <th>{t('segments.english')}</th>
                <th>{t('segments.german')}</th>
                <th>{t('segments.fit')}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((segment) => (
                <SegmentRow
                  key={segment.id}
                  segment={segment}
                  selected={segment.id === selected?.id}
                  onSelect={() => {
                    setSelectedId(segment.id);
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
        {selected ? (
          <SegmentEditor key={selected.id} projectId={projectId} segment={selected} />
        ) : (
          <div className="card empty">{t('segments.noMatches')}</div>
        )}
      </div>
    </section>
  );
}

function SegmentRow({
  segment,
  selected,
  onSelect,
}: {
  segment: Segment;
  selected: boolean;
  onSelect: () => void;
}) {
  const t = useT();
  return (
    <tr aria-selected={selected}>
      <td className="segments__time">
        <button
          className="link mono"
          type="button"
          aria-label={t('segments.editLabel', { number: segment.ordinal + 1 })}
          onClick={onSelect}
        >
          {formatTimestamp(segment.start_ms)}
        </button>
      </td>
      <td>{segment.source_text}</td>
      <td>
        {segment.translation ?? <span className="muted">{t('segments.notTranslated')}</span>}
        {segment.flags.length > 0 && (
          <div className="row flag-list">
            {segment.flags.map((flag) => (
              <span className="badge badge--warn" key={flag}>
                {describeFlag(flag)}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="segments__fit">
        {segment.fit ? formatDeviation(segment.fit.deviation) : '—'}
      </td>
    </tr>
  );
}
