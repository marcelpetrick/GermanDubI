import { ApiError } from '@/api/client';

function messageFor(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return 'Something went wrong.';
}

/** Render an actionable API or client error without leaking implementation details. */
export function ErrorAlert({ error }: { error: unknown }) {
  return (
    <div className="alert alert--error" role="alert">
      {messageFor(error)}
    </div>
  );
}
