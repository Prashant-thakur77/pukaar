import { useCallback, useEffect, useRef, useState } from 'react';

export type RecorderError = 'unsupported' | 'denied' | 'failed';

export interface UseMediaRecorderResult {
  isRecording: boolean;
  isSupported: boolean;
  error: RecorderError | null;
  audioBlob: Blob | null;
  elapsedMs: number;
  /** 0..1 loudness samples for a live waveform (most recent last). */
  levels: number[];
  start: () => Promise<void>;
  stop: () => void;
  reset: () => void;
}

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
const BARS = 28;

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported?.(m));
}

/** Records one voice clip, stopping on its own at `maxMs`. */
export function useMediaRecorder(maxMs = 20000): UseMediaRecorderResult {
  const isSupported =
    typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';

  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<RecorderError | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [levels, setLevels] = useState<number[]>(() => Array(BARS).fill(0));

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const rafRef = useRef<number | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const startRef = useRef(0);
  const mimeRef = useRef('audio/webm');

  const cleanup = useCallback(() => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void ctxRef.current?.close().catch(() => {});
    ctxRef.current = null;
  }, []);

  const stop = useCallback(() => {
    const rec = recorderRef.current;
    if (rec && rec.state !== 'inactive') {
      try {
        rec.stop();
        return;
      } catch {
        setError('failed');
      }
    }
    cleanup();
    setIsRecording(false);
  }, [cleanup]);

  const start = useCallback(async () => {
    setError(null);
    if (!isSupported) {
      setError('unsupported');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      mimeRef.current = mimeType?.split(';')[0] ?? 'audio/webm';
      const rec = mimeType ? new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 24000 }) : new MediaRecorder(stream);
      recorderRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = (e: BlobEvent) => {
        if (e.data?.size) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        setAudioBlob(new Blob(chunksRef.current, { type: mimeRef.current }));
        cleanup();
        setIsRecording(false);
      };
      rec.onerror = () => {
        setError('failed');
        cleanup();
        setIsRecording(false);
      };

      // Live waveform from an analyser; optional, recording works without it.
      let analyser: AnalyserNode | null = null;
      try {
        const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (Ctx) {
          const ctx = new Ctx();
          ctxRef.current = ctx;
          analyser = ctx.createAnalyser();
          analyser.fftSize = 512;
          ctx.createMediaStreamSource(stream).connect(analyser);
        }
      } catch {
        analyser = null;
      }
      const buf = analyser ? new Uint8Array(analyser.fftSize) : null;
      let lastPush = 0;

      startRef.current = performance.now();
      setElapsedMs(0);
      setAudioBlob(null);
      setLevels(Array(BARS).fill(0));
      rec.start(1000);
      setIsRecording(true);

      const tick = (now: number) => {
        const elapsed = now - startRef.current;
        setElapsedMs(elapsed);
        if (analyser && buf && now - lastPush > 70) {
          lastPush = now;
          analyser.getByteTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = (buf[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.min(1, Math.sqrt(sum / buf.length) * 3.2);
          setLevels((prev) => [...prev.slice(1), rms]);
        }
        if (elapsed >= maxMs) {
          stop();
          return;
        }
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch (err) {
      cleanup();
      setIsRecording(false);
      const name = (err as DOMException | null)?.name;
      setError(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'failed');
    }
  }, [isSupported, cleanup, maxMs, stop]);

  const reset = useCallback(() => {
    setAudioBlob(null);
    setElapsedMs(0);
    setError(null);
    setLevels(Array(BARS).fill(0));
  }, []);

  useEffect(
    () => () => {
      const rec = recorderRef.current;
      if (rec && rec.state !== 'inactive') {
        rec.onstop = null;
        try {
          rec.stop();
        } catch {
          /* ignore */
        }
      }
      cleanup();
    },
    [cleanup],
  );

  return { isRecording, isSupported, error, audioBlob, elapsedMs, levels, start, stop, reset };
}
