import { useState } from 'react';

import type { Segment, SegmentList } from '@/api/types';
import { ErrorAlert } from '@/components/ErrorAlert';
import { SegmentEditor } from '@/features/segments/SegmentEditor';
import { describeFlag, formatDeviation, formatTimestamp } from '@/lib/format';

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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  if (loading) return <section className="card muted">Loading segments…</section>;
  if (error) return <ErrorAlert error={error} />;
  if (!data || data.segments.length === 0) return null;

  const selected = data.segments.find((segment) => segment.id === selectedId) ?? data.segments[0];
  if (!selected) return null;

  return (
    <section className="stack" aria-labelledby="segments-heading">
      <div className="card segment-summary">
        <div>
          <h2 id="segments-heading">Review segments</h2>
          <p className="muted small">
            Select a row, correct one text field, and regenerate only its downstream work.
          </p>
        </div>
        <div className="row small">
          <span>{data.summary.total} total</span>
          <span>{data.summary.approved} approved</span>
          <span className={data.summary.flagged ? 'badge badge--warn' : 'badge'}>
            {data.summary.flagged} flagged
          </span>
          <span className={data.summary.failed ? 'badge badge--danger' : 'badge'}>
            {data.summary.failed} failed
          </span>
        </div>
      </div>
      <div className="split">
        <div className="card table-scroll">
          <table className="segments">
            <thead>
              <tr>
                <th>Time</th>
                <th>English</th>
                <th>German</th>
                <th>Fit</th>
              </tr>
            </thead>
            <tbody>
              {data.segments.map((segment) => (
                <SegmentRow
                  key={segment.id}
                  segment={segment}
                  selected={segment.id === selected.id}
                  onSelect={() => {
                    setSelectedId(segment.id);
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
        <SegmentEditor key={selected.id} projectId={projectId} segment={selected} />
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
  return (
    <tr aria-selected={selected}>
      <td className="segments__time">
        <button
          className="link mono"
          type="button"
          aria-label={`Edit segment ${String(segment.ordinal + 1)}`}
          onClick={onSelect}
        >
          {formatTimestamp(segment.start_ms)}
        </button>
      </td>
      <td>{segment.source_text}</td>
      <td>
        {segment.translation ?? <span className="muted">Not translated</span>}
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
