// Copies data files the web pages read into public/: the back-test results written by the backend
// (data/backtest.json, for /impact) and the hand-kept pilot-readiness checklist (data/pilot_readiness.json,
// for /pilot). A missing file is fine: the page then says "not yet available".
import { copyFileSync, existsSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

for (const name of ['backtest.json', 'pilot_readiness.json']) {
  const src = fileURLToPath(new URL(`../../data/${name}`, import.meta.url));
  const dst = fileURLToPath(new URL(`../public/${name}`, import.meta.url));
  if (existsSync(src)) {
    copyFileSync(src, dst);
    console.log(`${name} copied to public/`);
  } else {
    if (existsSync(dst)) rmSync(dst);
    console.log(`no data/${name}; the page will show "not yet available"`);
  }
}
