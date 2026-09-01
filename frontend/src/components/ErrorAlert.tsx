import { ApiError } from '@/api/client';
import type { TranslationKey } from '@/i18n/en';
import { useT } from '@/i18n/LocaleProvider';
import { CATALOGUES } from '@/i18n/locales';

/** Error codes with a heading of their own; anything else falls back to the generic one. */
function headingKey(code: string): TranslationKey {
  const candidate = `error.code.${code}`;
  return (candidate in CATALOGUES.en ? candidate : 'error.code.internal_error') as TranslationKey;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

/**
 * Render an actionable API or client error without leaking implementation details.
 *
 * The heading is translated from the error's stable code. The server's own sentence is
 * shown underneath in the language the server speaks: it is the specific diagnostic a user
 * quotes when asking for help, and mirroring the backend's whole message catalogue here
 * would drift out of date within a release.
 *
 * When the server did not anticipate the failure it also sends a reference and the path of
 * its log. Both are shown, because "check the server log" without saying which log or where
 * is not an instruction.
 */
export function ErrorAlert({ error }: { error: unknown }) {
  const t = useT();
  const api = error instanceof ApiError ? error : null;
  const heading = api ? t(headingKey(api.code)) : t('error.title');
  const detail = error instanceof Error ? error.message : null;
  const reference = api ? asString(api.details.reference) : null;
  const logFile = api ? asString(api.details.log_file) : null;

  return (
    <div className="alert alert--error" role="alert">
      <strong>{heading}</strong>
      {detail && detail !== heading && <p className="alert__detail">{detail}</p>}
      {reference && (
        <p className="muted small">
          {t('error.reference', { reference })}
          {' · '}
          {logFile ? t('error.logAt', { path: logFile }) : t('error.logInTerminal')}
        </p>
      )}
    </div>
  );
}
