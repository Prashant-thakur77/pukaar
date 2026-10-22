import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { statusPagePlugin } from './status-page';

export default defineConfig({
  plugins: [
    react(),
    statusPagePlugin(),
    VitePWA({
      registerType: 'autoUpdate',
      devOptions: { enabled: false },
      includeAssets: ['favicon.svg'],
      manifest: {
        name: 'Pukaar पुकार — flood warnings for Himalayan villages',
        short_name: 'पुकार Pukaar',
        description:
          'नदी से पहले गाँव तक पहुँचने वाली पुकार। The call that reaches the village before the river does: approved, spoken Hindi flood alerts and voice reports.',
        lang: 'hi',
        dir: 'ltr',
        theme_color: '#0b1026',
        background_color: '#0b1026',
        display: 'standalone',
        start_url: '/report',
        scope: '/',
        icons: [{ src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
        shortcuts: [
          { name: 'सूचना दें · Report', url: '/report' },
          { name: 'लाइव · Live', url: '/live' },
        ],
      },
      // A hand-written worker (src/sw.ts) so it can handle Web Push for officers. It keeps what
      // the generated worker did: navigation fallback to /index.html (never /api/), the OSM and
      // elevation tile caches, cleanup of old precaches, skipWaiting + clientsClaim (autoUpdate).
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectManifest: {
        // The app shell (including /report and its fonts) is precached so the
        // report page opens with no network; API calls are never cached. Left out, so a
        // phone on 2G does not download them in the background on its first visit:
        // MapLibre and the 3D hero; Noto Sans Devanagari (120 kB, and a system font on
        // Android, see theme.css) and the display italic; and the officer and explainer
        // pages, which load on demand as before.
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        globIgnores: [
          '**/maplibre*', '**/HeroScene*', '**/*latin-ext*', '**/*cyrillic*', '**/*greek*', '**/*vietnamese*',
          '**/noto-sans-devanagari*', '**/*italic*',
          '**/ConsolePage-*', '**/Roster-*', '**/Audit-*', '**/Pilot-*', '**/Impact-*', '**/Agents-*', '**/How-*', '**/Sensors-*',
        ],
        maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
        // One classic script, as registerSW.js registers it.
        rollupFormat: 'iife',
      },
    }),
  ],
  build: {
    // MapLibre (~990 kB) is a lazy chunk loaded only on map pages.
    chunkSizeWarningLimit: 1100,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
});
