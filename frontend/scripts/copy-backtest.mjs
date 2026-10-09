// Copies the back-test results written by the backend (data/backtest.json)
// into public/ so the Impact page can load /backtest.json. Missing file is fine:
// the page then says "not yet available".
import { copyFileSync, existsSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const src = fileURLToPath(new URL('../../data/backtest.json', import.meta.url));
const dst = fileURLToPath(new URL('../public/backtest.json', import.meta.url));
if (existsSync(src)) {
  copyFileSync(src, dst);
  console.log('backtest.json copied to public/');
} else {
  if (existsSync(dst)) rmSync(dst);
  console.log('no data/backtest.json; Impact page will show "not yet available"');
}
