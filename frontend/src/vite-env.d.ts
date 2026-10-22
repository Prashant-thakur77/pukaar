/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_COGNITO_CLIENT_ID?: string;
  readonly VITE_COGNITO_REGION?: string;
  /** AppSync Events (live push); all three or none. The key is public and subscribe-only. */
  readonly VITE_EVENTS_HTTP_DOMAIN?: string;
  readonly VITE_EVENTS_REALTIME_DOMAIN?: string;
  readonly VITE_EVENTS_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** One language's UI strings, split from i18n/strings.ts at build time (i18n-plugin.ts). */
declare module 'virtual:pk-strings/*' {
  const table: Record<string, string>;
  export default table;
}
