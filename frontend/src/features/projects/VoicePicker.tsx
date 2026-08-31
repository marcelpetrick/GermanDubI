import { useRef, useState } from 'react';

import { api } from '@/api/client';
import { useVoices } from '@/hooks/queries';
import { useT } from '@/i18n/LocaleProvider';

/**
 * Choose the German narrator, and hear it first.
 *
 * A list of identifiers like `de_DE-pavoque-low` asks someone to choose a narrator they
 * have never heard. The play button is the part that makes the list answerable, so it sits
 * next to the choice rather than behind a link.
 */
export function VoicePicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (voice: string | null) => void;
}) {
  const t = useT();
  const voices = useVoices();
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  if (!voices.data || voices.data.length === 0) return null;

  const selected = value ?? voices.data[0]?.id ?? null;

  const preview = () => {
    if (!selected) return;
    setFailed(false);
    audio.current?.pause();
    // A voice that is not downloaded yet is fetched on demand, so the first play of one
    // can take a while. Saying it is loading beats a button that appears to do nothing.
    setPlaying(selected);
    const element = new Audio(api.voiceSampleUrl(selected));
    audio.current = element;
    element.onended = () => {
      setPlaying(null);
    };
    element.onerror = () => {
      setPlaying(null);
      setFailed(true);
    };
    void element.play().catch(() => {
      setPlaying(null);
      setFailed(true);
    });
  };

  return (
    <div className="voice-picker">
      <label className="voice-picker__label" htmlFor="voice">
        {t('voice.label')}
      </label>
      <div className="row">
        <select
          id="voice"
          className="select-inline voice-picker__select"
          value={selected ?? ''}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        >
          {voices.data.map((voice) => (
            <option key={voice.id} value={voice.id}>
              {voice.speaker} · {voice.quality}
              {voice.downloaded ? '' : ` · ${t('voice.notDownloaded')}`}
            </option>
          ))}
        </select>
        <button type="button" onClick={preview} disabled={playing !== null}>
          {playing !== null ? t('voice.loading') : t('voice.play')}
        </button>
      </div>
      <p className="muted small">{failed ? t('voice.sampleFailed') : t('voice.hint')}</p>
    </div>
  );
}
