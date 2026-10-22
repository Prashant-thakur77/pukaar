#!/usr/bin/env node
// The Content-Security-Policy allows index.html's inline script and style by hash (no 'unsafe-inline'): the
// theme guard, the boot painter and the critical CSS (boot-plugin.ts). A build lists the hashes it needs in
// dist/csp-inline.json. This script writes them into infra/template.yaml (AmplifyApp CustomHeaders):
//   node scripts/csp-sync.mjs           update the template's script-src and style-src, and csp-hashes.json
//   node scripts/csp-sync.mjs --check   exit 1 if the template does not allow this build (deploy_web.sh, check:csp)
// frontend/csp-hashes.json is the committed copy the backend's template test reads (no build there).
// If the hashes are missing the site still works, but slower: the browser blocks the inline painter and the
// critical CSS, and the deferred pk-fallback script starts the app the ordinary way.
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const TEMPLATE = fileURLToPath(new URL('../../infra/template.yaml', import.meta.url));
const INLINE = fileURLToPath(new URL('../dist/csp-inline.json', import.meta.url));
const COMMITTED = fileURLToPath(new URL('../csp-hashes.json', import.meta.url));
const check = process.argv.includes('--check');

const need = JSON.parse(readFileSync(INLINE, 'utf8'));
const text = readFileSync(TEMPLATE, 'utf8');
const line = text.match(/(- key: Content-Security-Policy\s*\n\s*value: ")(.*)(")/);
if (!line) {
  console.error('csp-sync: no Content-Security-Policy header in infra/template.yaml');
  process.exit(2);
}
const policy = line[2];

/** The directive with exactly 'self' and these hashes, everything else it had kept. */
function withHashes(p, directive, hashes) {
  const re = new RegExp(`(^|; )${directive} ([^;]*)`);
  const m = p.match(re);
  if (!m) throw new Error(`no ${directive} in the policy`);
  const kept = m[2].split(/\s+/).filter((t) => t && !t.startsWith("'sha256-"));
  return p.replace(re, `${m[1]}${directive} ${[...kept, ...hashes].join(' ')}`);
}

const has = (directive, hashes) => {
  const m = policy.match(new RegExp(`(?:^|; )${directive} ([^;]*)`));
  const got = new Set((m?.[1] ?? '').split(/\s+/));
  return hashes.filter((h) => !got.has(h));
};
const missing = [...has('script-src', need.script), ...has('style-src', need.style)];

if (check) {
  if (missing.length) {
    console.error(`csp-sync: infra/template.yaml does not allow this build's inline ${missing.length === 1 ? 'block' : 'blocks'}: ${missing.join(' ')}`);
    console.error('  run: node scripts/csp-sync.mjs   (then deploy the stack so Amplify sends the new policy)');
    process.exit(1);
  }
  console.log(`csp-sync: the template allows all ${need.script.length + need.style.length} inline blocks of this build`);
  process.exit(0);
}

writeFileSync(COMMITTED, `${JSON.stringify({ script: [...need.script].sort(), style: [...need.style].sort() }, null, 2)}\n`);
const next = withHashes(withHashes(policy, 'script-src', need.script), 'style-src', need.style);
if (next === policy) {
  console.log('csp-sync: infra/template.yaml already allows this build');
} else {
  writeFileSync(TEMPLATE, text.replace(line[0], `${line[1]}${next}${line[3]}`));
  console.log(`csp-sync: infra/template.yaml now allows script ${need.script.join(' ')} and style ${need.style.join(' ')}`);
}
