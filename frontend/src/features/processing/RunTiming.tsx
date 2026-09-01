import { useEffect, useState } from 'react';

import type { Run } from '@/api/types';
import { useLocale, useT } from '@/i18n/LocaleProvider';
import { elapsedMs, formatClock, formatDuration } from '@/lib/format';

/** How often the "running for" figure is recomputed. */
const TICK_MS = 1000;

/**
 * When a run started, when it ended, and how long it took.
 *
 * Both numbers were already recorded and neither was ever shown, so the only way to answer
 * "how long did that dub take" was to read the log. A run that is still going counts up
 * instead, which also distinguishes a slow stage from a stopped one at a glance.
 */
export function RunTiming({ run }: { run: Run }) {
  const t = useT();
  const { locale } = useLocale();
  const finished = run.finished_at ?? null;
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    // Only a live run needs a clock; a finished one never changes again.
    if (finished) return undefined;
    const timer = window.setInterval(() => {
      setNow(new Date());
    }, TICK_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [finished]);

  const duration = elapsedMs(run.created_at, finished ?? now);
  const parts = [t('run.started', { time: formatClock(run.created_at, locale, now) })];
  if (finished) parts.push(t('run.finished', { time: formatClock(finished, locale, now) }));
  if (duration !== null) {
    parts.push(
      finished
        ? t('run.took', { elapsed: formatDuration(duration) })
        : t('run.running', { elapsed: formatDuration(duration) }),
    );
  }

  return (
    <span className="muted small run-timing">
      <time dateTime={run.created_at}>{parts.join(' · ')}</time>
    </span>
  );
}
