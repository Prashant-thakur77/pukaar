# UI notes: studying EcoLafaek for Pukaar

These notes come from a Playwright pass on 2026-10-09. Every page was loaded at 390x844 (phone) and 1440x900 (desktop), scrolled slowly to the bottom, and captured full page. I also read computed styles, `document.getAnimations()` and the `@keyframes` rules. Screenshots are in `/home/user/refs/ui-study/` (outside the repo). Everything below describes what showed up in those screenshots. We are borrowing patterns only, not their logos, images or wording.

## What loaded

| Site | Result |
|---|---|
| www.ecolafaek.com (home, /achievements, /about, /download, /contact) | Loaded fully at both sizes |
| dashboard.ecolafaek.com | Loaded, but every route sits behind an email one-time-code sign-in. I did not sign up, so the nav, the AI agent and the two test questions **could not be reached**. Only the sign-in screen is documented. |
| report.ecolafaek.com | Loaded. On desktop it shows a "phone only" screen. On a phone I walked it with a fake camera and GPS up to the review screen, with every non-GET request blocked. **Nothing was submitted.** |
| binmap.ecolafaek.com | Phone UA: the map loaded. Desktop (headless UA): HTTP 403 "Automated access is not allowed". I respected that and did not interact with the map. |
| docs.ecolafaek.com | Vercel `404 DEPLOYMENT_NOT_FOUND`, so the docs site is down |

## The two visual systems

EcoLafaek runs two separate design languages:

1. **Marketing site (www): an editorial poster style.** Anton is the display face: condensed, all caps, very large (h1 124px, section h2 130px on desktop, about 66px on phone). Inter is the body face. Each section is a full-bleed colour band: near-black `#0C0C0B`, mustard gold `#D8AD55`, deep forest `#0D4A33`, crimson `#A3141A`, warm paper `#F8F5EE`/`#F4EFE4`. Small labels above headings are gold, letter-spaced 0.3em, about 11px. Pill buttons (`9999px`) use 11px/900 uppercase tracked text. Cards use a 28px radius, phone mockups 36px. A grain overlay sits on top (`s-grain`, 0.9s steps(4), infinite).
2. **Product apps (dashboard, report, binmap): a soft "app" style.** Poppins only. Pale mint-white background `#F6FAF6`, primary green `#1B7F3A` with `#34A853` for accents and `#1B5E20` for headings. White cards with 14–20px radii, pill chips, and green-tinted shadows (for example `rgba(27,94,32,.06)` and `rgba(20,138,67,.7) 0 6px 16px -8px`). It feels friendly and Material-ish.

## Page by page

### Home (www)
- **Nav:** dark sticky bar. Wordmark on the left, centred links in 11px tracked caps (How it works · Achievements · About · Download · Contact), and a gold pill "Dashboard ↗" on the right. On a phone the links collapse into a round outlined hamburger.
- **Intro splash** (plays on every marketing page load, about 2.6s, with a "Skip intro" button bottom right): dark green radial vignette. The island outline is drawn as a gold stroke (`introDraw` with stroke-dashoffset), then fills green. A small mascot circles it on a gold trail while concentric ellipse ripples expand (`introRipple` 2.6s ease-out, scale 0.55→2.1, opacity .5→0). Then the logo badge pops in with overshoot (`introLogoPop` 0.6s `cubic-bezier(.34,1.56,.64,1)`), a ring pulses (`introRingPulse` 1.6s), the tagline rises (`introRise` 14px), a rule grows (`introGrow` scaleX), and the scene scales to 1.18 and fades (`introSceneOut` 0.6s ease-in).
- **Hero:** dark photo background, dimmed to 25% opacity, with a slow parallax translate on scroll. Two columns, about 56/44. On the left: a gold eyebrow, a three-line Anton headline with the last line in gold, a 20px paragraph at 75% white, then a gold pill CTA next to an outlined pill. On the right: a tilted phone mockup with two floating stat chips (a gold block "262 reports analysed" and a white block "0 reports today"). On a phone everything stacks and the mockup sits under the CTAs.
- **Counter band:** full-width gold strip with four stats in a 4-col grid. Each stat has a black top rule, a huge Anton number with "+", and a tracked caps label. The numbers **count up from 0** on load (done within about 3s). On a phone they stack into 1 column.
- **How it works:** cream section. The giant heading "HOW IT WORKS" **slides in horizontally from the left as you scroll** (scroll-linked, so it bleeds off the left edge in the full-page capture). Next to it sits a short paragraph. Below are 3 black cards (28px radius), each with a gold Anton "01/02/03" and a phone screenshot, then an Anton h3 and body text under the card. The cards fade and rise slightly, staggered, driven by scroll (opacity .93→1, translateY 4px→0).
- **"Built for every street":** forest-green band. Big heading slides in. Its paragraph uses a **word-by-word scroll-scrubbed reveal**: each word is its own span whose opacity goes from about 0.3 to 1 as you scroll. Below is a 3-col grid of tool tiles separated by 1px hairlines (a `gap-px` trick inside a 28px-radius container). Each tile has a gold eyebrow, an Anton title, body text and a mint "OPEN →" link. One tile holds a map screenshot. On a phone it becomes a single column list with hairline dividers.
- **Bin map teaser:** cream. Text on the left with a "NEW" pill, a black pill and an outline pill. A large browser-frame screenshot of the map sits on the right.
- **Problem statement:** crimson band. Heading slides in on the left; on the right a large paragraph with the same scrubbed word reveal and a small tracked "source" line.
- **CTA:** black band with a heading, a paragraph and two pills. On the right a cream rounded card (about 28px radius) with a QR code and "Scan to download".
- **Footer:** black. A brush-script slogan in gold, three link columns with tracked caps headers, and a giant wordmark in tan that spans the full width at the bottom. Below it a thin rule and a three-part meta row.
- Layout uses `max-w-[1500px]` with about 40px side padding on desktop and a 12-col grid in the footer. Section padding is very generous, roughly 120–160px vertically.
- Libraries: Next.js plus Tailwind. Inline `translate: none; rotate: none; scale: none; transform: …` on the animated nodes is the signature of **GSAP ScrollTrigger**. No Lottie, AOS or Three.js.

### Achievements
- A scroll-driven "story" page, about 14,700px tall on desktop, in chapters. Its own top nav lists chapters (Dili · The build · Agents League · Las Vegas · World tour · Honoured at home · Manila) plus "← EcoLafaek" and "Dashboard ↗". The opening is "FROM / DILI" top left and "TO THE / WORLD" top right, with a **dot-matrix world map** in between and a dotted arc running from a pin at home to a glowing pin far away. A "Sound on" toggle and a marquee ticker (`ach-marquee` 28s linear) sit underneath.
- Chapters are **pinned full-screen sections** with long scroll distances. Large stretches look empty in a static capture because content animates in while pinned. Each chapter changes the background: deep maroon with a huge red brush-lettered place name and a tilted phone, then saturated yellow `#F3C31B` with a tilted stage photo, then red and green. The yellow chapter uses Anton titles paired with a muted paragraph that reveals as you scroll.
- Chart.js or canvas is present (canvas detected). Radii are mostly tiny (1–2px), which gives it an editorial, print-like feel.

### About
- Dark hero: a two-tone Anton "THE STORY OF / ECOLAFAEK" (white then gold) with a gold **brush-script line overlapping** the bottom of the headline. Then the gold 4-stat band again (no counting here), a crimson mission band (sliding heading plus scrubbed paragraph), and a cream 4-col "01–04" process row. That row uses **outlined Anton numerals** (stroke only) with vertical hairline dividers.
- "Our technology": a black section of grouped cards (`rgba(255,255,255,.04)` fill, 1px white/10 ring, 16–22px radius). Each card has an icon tile, an Anton title, a gold tracked subtitle and body text, in a 4-col grid. Group labels are tracked caps with a hairline under them. Below them a green 4-col feature strip.
- FAQ: a cream accordion with Anton questions and a +/× toggle, hairline rules between items, and a big sliding "QUESTIONS" heading on the left.
- Closing forest-green CTA with a centred Anton headline.

### Download
- Same intro splash. Dark hero "CARRY … IN YOUR POCKET". Two overlapping phone mockups on the left. On the right a white 28px-radius card with an Android/iPhone segmented pill toggle, a QR code, "Scan to download", a black pill CTA, an outline pill, and a version line split by a hairline.
- "Everything you need to act": 4 cards (green top half holding a phone crop, dark bottom half with an Anton title and text).
- "Three steps": gold band, 3 columns with black top rules, **outlined Anton numerals**, a title and text, and a black pill "Download now". On a phone the band is 1 column.

### Contact
- A row of 4 coloured contact tiles (crimson, charcoal, green, gold), each with an arrow, used as quick links. A cream form section: on the left a big sliding heading; on the right **underline-only inputs** with tracked caps labels in a 2-col row for name and email, a select, a subject line, a textarea, and a black pill "Send message →". Form focus uses `border-color .2s ease`.

### Dashboard (dashboard.ecolafaek.com)
- **Only the sign-in screen was reachable.** Desktop is a 50/50 split. On the left a green-tinted aerial photo with the logo tile, a 36px Poppins bold headline, a lead paragraph, a 3-item check list and a small footer line. On the right, on mint-white, "Sign in" (24px, dark green), helper text, an email input with a mail icon and 18px radius, a full-width pill "Send me a code →" (pale green while disabled), and a small shield-icon note about session length.
- On a phone the photo panel is dropped. The logo tile, name and subtitle are centred above the form.
- Nav items, maps, filters, charts and the AI agent all sit behind sign-in. **The two questions could not be asked.** The marketing copy says the agent returns charts and maps in answer to plain-language questions, so we do not have its real response format.

### Report (report.ecolafaek.com)
- **Desktop:** one centred white card (about 450px wide, about 20px radius, soft shadow) on mint-white with an illustration, "Open this page on your phone", an explanation, and a mint inset box holding the URL. This is a deliberate **device-gate state**.
- **Phone flow, 3 screens, with submit on the third:**
  1. **Intro:** logo plus name and tagline; a photo hero card (28px radius, dark gradient overlay, eyebrow, 26px bold headline, short line); a white "How it works" card with 3 numbered green circles, each with an icon and a line; a pale green "follow your reports, get the app" card with an outline button; a privacy note; a rate-limit note; and a **sticky full-width green "Take Photo" button** at the bottom.
  2. **Camera:** full-screen live camera with an × at the top left, a centred title and subtitle, a dark translucent tip banner ("make sure the waste is clearly visible"), white corner brackets for a viewfinder, a large round shutter (white ring with a green core), and a bottom bar showing the reverse-geocoded place, coordinates and a green "✓ GPS ready".
  3. **Review:** back button, title "Review Report", the photo at a 20px radius with a "Retake" pill overlaid, a green "Photo looks good!" check card, a location card with an embedded mini map (pin plus zoom controls), an optional description textarea with a 0/200 counter, a "Helpful tips" card, and a **sticky "Submit Report"** button with a footnote. *(We stopped here.)*
- **Error state captured:** "Camera unavailable". A black screen with an illustration, a bold title, one plain sentence, a green "Try again" button, and the disabled shutter dimmed. The GPS bar stays visible. This is a good model for errors: friendly, one action.
- No CSS animations were detected. Motion here is plain screen swapping.

### BinMap (binmap.ecolafaek.com, phone only)
- A **full-bleed Leaflet map** with CARTO light tiles, taking about 80% of the viewport. Floating over it: a white rounded search bar, a horizontally scrolling row of **filter chips** (the active one solid green, the others white pills with coloured dot icons), and on the right a column of white rounded square controls (layers, +/−, locate me). Markers are purple teardrop pins with a bin glyph and small green or yellow status dots.
- A **bottom sheet peek** ("48 bins mapped · tap for statistics and filters", with a chevron, 24px top radius) sits above a **bottom tab bar** with a raised circular green centre action ("Add Bin"). Header: logo, name with a pin glyph, and an outline "Login" pill.

### Docs
- Down (404 DEPLOYMENT_NOT_FOUND), so there is nothing to study.

## Loading, empty and error states seen
- Marketing pages: the intro splash doubles as the loader, and it can be skipped.
- Counters render "0" first, then count up.
- Report: device gate (desktop), camera error with a retry, "GPS ready" confirmation, a disabled primary button (pale green) until input is valid.
- Dashboard: disabled "Send me a code" until an email is entered.
- No skeletons were seen, because the dashboard was not reachable.

## Motion inventory (measured)
| Motion | Where | Timing |
|---|---|---|
| Stroke-draw outline, then fill | intro | 0.9s ease-out draw, 2.6s linear trail |
| Ripple rings | intro | 2.6s ease-out, scale .55→2.1, fade .5→0, 3 staggered |
| Logo pop with overshoot | intro | 0.6s `cubic-bezier(.34,1.56,.64,1)` |
| Ring pulse | intro | 1.6s ease-out, scale 1→1.25, fade |
| Scene exit zoom-fade | intro | 0.6s ease-in, scale 1→1.18 |
| Count-up numbers | stat band | about 1.5–2.5s on load or in view |
| Heading slide-in from left | section h2s | scroll-scrubbed (GSAP) |
| Word-by-word opacity reveal | lead paragraphs | scroll-scrubbed |
| Card rise and fade, staggered | how-it-works cards | scroll-scrubbed, about 24px |
| Hero image parallax | hero | scroll-scrubbed, small Y shift |
| Film grain | whole site | 0.9s steps(4), infinite |
| Marquee | achievements | 28s linear, infinite |
| Hover | links, buttons | colour 150ms `cubic-bezier(.4,0,.2,1)`, transform 150ms |
| Others defined | floatSlow/floatSlower blobs, glowPulse, sheen, shimmer, spinSlow | ambient |

## Patterns we take
1. **Two design registers:** an expressive public storytelling site and a calm, functional app. Same palette family, different intensity.
2. **Full-bleed colour bands** to separate sections, plus generous vertical rhythm (120px+ on desktop).
3. **A stat band with big numbers that count up,** each with a hairline rule on top and a small tracked label.
4. **A numbered three-step "how it works"** with outlined numerals and a phone mockup per step.
5. **Hairline-divided tile grids** (`gap-px` on a tinted container) instead of many floating cards.
6. **A phone flow with a sticky full-width primary button,** numbered steps on the intro, and a review screen with a mini map before the final action.
7. **Friendly error states:** illustration, one sentence, one action, context (GPS) still visible.
8. **A full-bleed map with floating search, a chip filter row, round map controls and a bottom sheet peek over a tab bar** with a raised centre action.
9. **Eyebrow labels** (small tracked caps) above every heading.
10. **A skippable intro,** and `prefers-reduced-motion` handling (we must add this, see below).
11. **Underline inputs with tracked labels** for low-stakes forms; pill buttons everywhere.

## What we do differently (Pukaar's own identity)
1. **The wordmark is Devanagari "पुकार",** set in a strong Devanagari display face (for example Tiro Devanagari Hindi, Mukta ExtraBold or Hind Bold), with Latin "Pukaar" secondary. No condensed all-caps Latin poster type as the main voice. Hindi type needs more line height (about 1.5–1.6) and must not be letter-spaced.
2. **The motif is a call echoing across a Himalayan valley.** Concentric arcs and rings travel outward from the wordmark and bounce between layered ridge silhouettes. EcoLafaek uses a mascot and an island outline; we use sound waves and mountains. No mascot.
3. **A calm base palette:** snow/mist off-white, slate-blue ink, pine and river-teal for neutrals, rather than their loud gold/crimson/forest bands. Colour is **reserved for risk** so that alarm stays meaningful.
4. **Four risk levels, each always shown with icon + word + colour** (never colour alone):
   - सामान्य / Normal: green, check-circle
   - सतर्क / Watch: amber-yellow, eye
   - चेतावनी / Warning: orange, triangle-alert
   - गंभीर / Critical: deep red, siren or wave-alert

   They are used consistently in chips, map markers, banners and list rows.
5. **Villager pages are Hindi-first,** with large type (body 18px or more, primary actions 56px tall or more), few words and icon-led. English is a toggle, not the default. Pages work on low-end Android over 2G: no splash intro, no heavy images on villager pages, and only the cheap, informative motion described below.
6. **The emergency number 112 is always visible:** a persistent red-outline pill "आपातकाल 112" in the header and a tap-to-call FAB on every villager page, never hidden behind a menu.
7. **No sign-in wall for public risk info.** EcoLafaek gated the whole dashboard, and we found that a barrier. Public alert levels and the map are open; only admin tools need auth.
8. **The map is the hero of the authority dashboard.** Villages are drawn as risk-coloured markers with a pulse on Critical, and river gauges sit along the valley lines.
9. **Motion carries meaning,** for example a ring pulse equals an active alert. There is no decorative grain, marquee or ambient blob animation.

## Animation ideas for Pukaar
All of these respect `prefers-reduced-motion: reduce` (fall back to an instant state or a simple 150ms fade). They use `transform` and `opacity` only.

1. **Echo rings from the logo (hero, first load).** 3 concentric rings expand from "पुकार": scale 0.6→2.2 and opacity 0.45→0, staggered 400ms. Duration 2.4s, `cubic-bezier(.22,1,.36,1)` (ease-out-quint). Plays once, then a single faint ring every 6s while the page is idle.
2. **Valley echo bounce (hero background).** A ring arc travels to the left ridge silhouette, then a weaker arc returns to the right ridge at 60% opacity, which reads as an echo. 1.8s per leg, ease-in-out. Plays once on load only.
3. **Ridge parallax.** 3 to 4 layered mountain silhouettes move at 0.1/0.2/0.35× the scroll speed. Scroll-linked, capped at about 40px of travel.
4. **Wordmark stroke draw.** The Devanagari शिरोरेखा (head-line) of पुकार draws left to right (stroke-dashoffset) before the letters fade in. 700ms ease-out, then letters 300ms fade, staggered 60ms.
5. **Counter count-up on scroll into view** (villages covered, sensors live, alerts sent). 1.4s `cubic-bezier(.16,1,.3,1)`, triggered at 40% visibility, once. Use Devanagari or Latin digits to match the locale.
6. **Staggered card reveal** (how-it-works steps and village cards). translateY 16px→0 with opacity 0→1, 450ms ease-out, 80ms stagger, IntersectionObserver, once.
7. **Critical-village map pulse.** On Critical markers a red ring scales 1→2.6 and fades 0.6→0, 1.6s ease-out, infinite. Warning markers get a slower amber ring (2.4s). Normal and Watch markers are static. Marker radius never changes, so the map stays readable.
8. **Risk level change morph.** When a village's level changes, the badge cross-fades colour, swaps its icon with a 200ms scale 0.8→1 using `cubic-bezier(.34,1.56,.64,1)` (gentle overshoot), and the row flashes a 600ms tinted background that fades out.
9. **Alert banner drop-in.** A Critical banner slides down from under the header (translateY −100%→0) over 320ms ease-out, with a one-shot 112 pill "nudge" (scale 1→1.06→1, 400ms). There is no infinite shaking.
10. **112 call button breathing.** A soft ring around the FAB, scale 1→1.35 and opacity 0.35→0 over 2.2s ease-out, repeating only while the user's village is at Warning or Critical.
11. **River level gauge fill.** Bar or area fills from 0 to the current value (scaleY with origin bottom, 900ms ease-out). Threshold lines for Watch, Warning and Critical fade in after it, staggered 100ms.
12. **Scrubbed sentence reveal (public site only).** The one mission sentence lights word by word as you scroll, like EcoLafaek's paragraphs, in Hindi. Opacity 0.25→1 per word, scroll-linked. Use it only once on the page.

## Screenshot index (`/home/user/refs/ui-study/`)
home-{mobile,desktop}.png, home-intro-{300,900,1600,2600}ms.png, home-scroll-desktop-y{0,900,1800,2700,3600,4500,5400}.png, achievements-{mobile,desktop}.png, about-{mobile,desktop}.png, download-{mobile,desktop}.png, contact-{mobile,desktop}.png, dashboard-{mobile,desktop}.png (sign-in only), report-{mobile,desktop}.png, report-step1-mobile.png (camera), report-step2-mobile.png (review, not submitted), report-error-camera-mobile.png, binmap-{mobile,desktop}.png (desktop = 403 block page), docs-{mobile,desktop}.png (404). Per-page style dumps are in the matching `*.json` files.
