/** Fired on window after a replay start or reset, so every replay view refreshes at once. */
export const REPLAY_EVENT = 'pukaar:replay';

export function announceReplayChange() {
  window.dispatchEvent(new Event(REPLAY_EVENT));
}
