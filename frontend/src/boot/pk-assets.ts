/** The app's own files, as boot-plugin.ts writes them into index.html (<script type="application/json" id="pk-assets">). */
export interface PkAssets {
  /** The entry module. */
  js: string;
  /** Its static imports, as module preloads. */
  pre: string[];
  /** The stylesheets every page needs, in cascade order. */
  css: string[];
  /** The extra stylesheets of the pages the painter draws (their chunks would load them later anyway). */
  answer: { home: string[]; village: string[] };
}
