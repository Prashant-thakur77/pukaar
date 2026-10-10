import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
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
      workbox: {
        // The app shell (including /report and its fonts) is precached so the
        // report page opens with no network; API calls are never cached. MapLibre
        // is left out so a phone on 2G does not download it in the background.
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        globIgnores: ['**/maplibre*', '**/HeroScene*', '**/*latin-ext*', '**/*cyrillic*', '**/*greek*', '**/*vietnamese*'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//],
        maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.hostname === 'tile.openstreetmap.org',
            handler: 'CacheFirst',
            options: { cacheName: 'osm-tiles', expiration: { maxEntries: 300, maxAgeSeconds: 7 * 24 * 3600 } },
          },
          {
            urlPattern: ({ url }) => url.hostname === 's3.amazonaws.com' && url.pathname.startsWith('/elevation-tiles-prod/'),
            handler: 'CacheFirst',
            options: { cacheName: 'dem-tiles', expiration: { maxEntries: 300, maxAgeSeconds: 30 * 24 * 3600 } },
          },
        ],
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
