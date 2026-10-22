// The no-JavaScript minimum for villagers. At build time this plugin reads /public/overview from the
// API (VITE_API_BASE) and writes each village's level, stamped with the build time, into:
//   - the <noscript> block of index.html (<!-- status:levels --> and <!-- status:links -->), which every
//     route serves, so /report and /village/<id> show it with scripts off;
//   - dist/status.html, a standalone page with no script at all.
// Both say plainly that the levels are from the build and not live, and link to the API's live, plain-text
// sources (the CAP feed and the overview), which a browser opens without JavaScript. No inline script or
// style: the page uses /noscript.css, so the Content-Security-Policy is unchanged.
import type { Plugin } from 'vite';

type Level = 'normal' | 'watch' | 'warning' | 'critical';
interface OverviewVillage {
  id: string;
  name: string;
  name_hi?: string;
  district?: string;
  level?: string;
  live_level?: string | null;
  data_status?: string;
}

const WORDS: Record<Level, [string, string]> = {
  normal: ['सामान्य', 'Normal'],
  watch: ['सतर्क', 'Watch'],
  warning: ['चेतावनी', 'Warning'],
  critical: ['गंभीर', 'Critical'],
};
const isLevel = (v: unknown): v is Level => typeof v === 'string' && v in WORDS;

export const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

/** "22 Oct 2026, 21:30 IST" */
export function istStamp(d: Date): string {
  const ist = new Date(d.getTime() + 330 * 60_000);
  const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][ist.getUTCMonth()];
  const hh = String(ist.getUTCHours()).padStart(2, '0');
  const mm = String(ist.getUTCMinutes()).padStart(2, '0');
  return `${ist.getUTCDate()} ${mon} ${ist.getUTCFullYear()}, ${hh}:${mm} IST`;
}

/** The levels list (or a line saying they could not be read at build time). */
export function levelsHtml(villages: OverviewVillage[] | null, builtAt: Date): string {
  const when = esc(istStamp(builtAt));
  const head =
    `<h2>गाँवों का स्तर, ${when} पर <span lang="en">· Village levels at ${when}</span></h2>\n` +
    `<p class="nojs-stale"><strong>यह लाइव नहीं है।</strong> यह स्तर तब का है जब यह पेज बना; अभी का स्तर इससे ऊँचा हो सकता है। ` +
    `<span lang="en">Not live: these are the levels when this page was built. The level now may be higher.</span></p>\n`;
  if (!villages?.length) return `${head}<p>स्तर पढ़े नहीं जा सके। <span lang="en">The levels could not be read when this page was built.</span></p>`;
  const rows = villages
    .map((v) => {
      const lv = isLevel(v.live_level) ? v.live_level : isLevel(v.level) ? v.level : null;
      const ok = !v.data_status || v.data_status === 'ok' || v.data_status === 'stale';
      const word = lv && ok ? `${WORDS[lv][0]} <span lang="en">· ${WORDS[lv][1]}</span>` : `डेटा उपलब्ध नहीं <span lang="en">· data unavailable</span>`;
      const name = v.name_hi ? `${esc(v.name_hi)} <span lang="en">· ${esc(v.name)}</span>` : esc(v.name);
      return `<li class="nojs-lv${lv && ok ? ` lv-${lv}` : ''}"><span class="nojs-v">${name}</span> <strong>${word}</strong></li>`;
    })
    .join('\n');
  return `${head}<ul class="nojs-levels">\n${rows}\n</ul>`;
}

/** Live sources that open without JavaScript, from the API itself. */
export function linksHtml(apiBase: string | undefined): string {
  if (!apiBase || !/^https?:\/\//.test(apiBase)) return '';
  const base = esc(apiBase.replace(/\/+$/, ''));
  return (
    `<h2>अभी का स्तर <span lang="en">· Levels now</span></h2>\n` +
    `<p>ये लिंक बिना JavaScript के खुलते हैं (सादा टेक्स्ट): <span lang="en">These open without JavaScript (plain text):</span></p>\n` +
    `<a class="nojs-link" href="${base}/cap/alerts.atom">जारी चेतावनियाँ (CAP) <span lang="en">· Alerts sent (CAP feed)</span></a>\n` +
    `<a class="nojs-link" href="${base}/public/overview">हर गाँव का स्तर <span lang="en">· Every village's level (overview)</span></a>`
  );
}

export function statusPage(builtAt: Date, levels: string, links: string): string {
  return `<!doctype html>
<html lang="hi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Pukaar पुकार · गाँवों का स्तर · Village levels</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<link rel="stylesheet" href="/noscript.css" />
</head>
<body>
<main class="nojs">
<p class="nojs-brand">पुकार <span lang="en">Pukaar</span></p>
<h1>बाढ़ या कोई ख़तरा? अभी 112 पर कॉल करें।</h1>
<p lang="en">Flood or any danger? Call 112 now.</p>
<a class="nojs-call" href="tel:112">112 पर कॉल करें · <span lang="en">Call 112</span></a>
${levels}
${links}
<h2>Telegram पर चेतावनी पाएँ <span lang="en">· Alerts on Telegram</span></h2>
<p>@PukaarRescuebot को <code lang="en">/start</code> और अपने गाँव का नाम भेजें, जैसे <code lang="en">/start thunag</code>।</p>
<a class="nojs-tg" href="https://t.me/PukaarRescuebot">Telegram: @PukaarRescuebot</a>
<p class="nojs-built">बना: ${esc(istStamp(builtAt))} <span lang="en">· Built ${esc(builtAt.toISOString())}</span></p>
</main>
</body>
</html>
`;
}

async function readOverview(apiBase: string | undefined): Promise<OverviewVillage[] | null> {
  if (!apiBase || !/^https?:\/\//.test(apiBase)) return null;
  try {
    const res = await fetch(`${apiBase.replace(/\/+$/, '')}/public/overview`, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) return null;
    const body = (await res.json()) as { villages?: OverviewVillage[] };
    return Array.isArray(body.villages) ? body.villages : null;
  } catch {
    return null;
  }
}

export function statusPagePlugin(): Plugin {
  let apiBase: string | undefined;
  let levels = '';
  let links = '';
  let builtAt = new Date();
  return {
    name: 'pukaar-status-page',
    apply: 'build',
    configResolved(config) {
      apiBase = config.env.VITE_API_BASE as string | undefined;
    },
    async buildStart() {
      builtAt = new Date();
      const villages = await readOverview(apiBase);
      this.info(villages ? `status page: ${villages.length} village levels from ${apiBase}` : 'status page: levels not available at build time');
      levels = levelsHtml(villages, builtAt);
      links = linksHtml(apiBase);
    },
    transformIndexHtml(html) {
      return html.replace('<!-- status:levels -->', levels).replace('<!-- status:links -->', links);
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'status.html', source: statusPage(builtAt, levels, links) });
    },
  };
}
