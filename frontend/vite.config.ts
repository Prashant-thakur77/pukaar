import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      devOptions: { enabled: false },
      manifest: {
        name: 'Pukaar',
        short_name: 'Pukaar',
        description: 'Alerta temprana de inundaciones',
        theme_color: '#0D3B2A',
        background_color: '#F3E9D2',
        display: 'standalone',
        start_url: '/',
        icons: [],
      },
    }),
  ],
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
});
