/** What the boot painter (boot.ts) leaves on window for the app. Types only, plus the key. */

export const BOOT_KEY = '__pkBoot';

/** A GET the boot painter started: the status and the parsed body, or a rejection with no network. */
export interface BootResult {
  ok: boolean;
  status: number;
  body: unknown;
}

export interface BootState {
  /** The boot painter's request for this API path, once, if it is younger than 30 s. */
  take(path: string): Promise<BootResult> | null;
  /** Whether the painter has a request for this path that the app has not taken yet. */
  has(path: string): boolean;
  /** The menu button was tapped before the app had drawn: open the sheet when it does. */
  menu: boolean;
}

export function bootState(): BootState | null {
  if (typeof window === 'undefined') return null;
  return ((window as unknown as Record<string, BootState | undefined>)[BOOT_KEY] as BootState | undefined) ?? null;
}
