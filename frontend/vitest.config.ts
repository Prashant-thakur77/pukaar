import { i18nStringsPlugin } from './i18n-plugin';

export default {
  plugins: [i18nStringsPlugin()],
  test: {
    environment: 'jsdom',
    pool: 'threads',
    maxWorkers: 1,
    fileParallelism: false,
    // Both language tables, loaded before any test renders a string (src/i18n.ts, loadLang).
    setupFiles: ['./src/test-setup.ts'],
  },
};
