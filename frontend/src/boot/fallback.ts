/*
 * A deferred external script (allowed by the CSP's 'self' whatever the inline hashes say): if the inline boot
 * painter did not run, for instance because its hash is missing from the Content-Security-Policy, it starts
 * the app the ordinary way, so the site is slower but never blank.
 */
import { loadApp, readAssets } from './assets';
import { BOOT_KEY } from './protocol';

if (!(BOOT_KEY in window)) {
  const a = readAssets();
  if (a) loadApp(a, null);
}
