import { loadLang } from './i18n';

await Promise.all([loadLang('hi'), loadLang('en')]);
