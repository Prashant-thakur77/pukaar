import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SirenPanel } from './SirenPanel';
import { SirenLastTested } from './SirenLastTested';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ALERT = {
  id: 'alr_1',
  village_id: 'thunag',
  village_name: 'Thunag',
  village_name_hi: 'थुनाग',
  level: 'warning',
  sirens_total: 1,
  sirens_started: 1,
  sirens_verified: 1,
};
const TIER = {
  total: 1,
  started: 1,
  verified: 1,
  pattern: 'W1',
  rows: [
    {
      device_id: 'siren-thunag-sim',
      round: 0,
      cmd_id: 'cmd_1',
      pattern: 'W1',
      level: 'warning',
      src: 'approval',
      status: 'verified',
      commanded_at: '2026-10-22T08:31:00Z',
      started_at: '2026-10-22T08:31:05Z',
      verified_at: '2026-10-22T08:31:09Z',
      meas: { amp_a: 3.1, spl_rise_db: 24 },
      simulated: true,
    },
  ],
};

let host: HTMLDivElement;
let root: Root;

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function mockApi(can: { test_siren: boolean; sound_siren: boolean; stop_siren: boolean }, sound: unknown = null) {
  const calls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url).pathname;
      calls.push(`${init?.method ?? 'GET'} ${path}`);
      if (path.endsWith('/sirens/sound')) return reply(sound, 202);
      if (path === '/alerts/alr_1/sirens') return reply(TIER);
      if (path === '/villages/thunag/devices')
        return reply({ village_id: 'thunag', devices: [{ device_id: 'siren-thunag-sim', kind: 'siren', health: 'ok' }], can, requests: [] });
      return reply({}, 404);
    }),
  );
  return calls;
}

async function flush() {
  for (let i = 0; i < 5; i++) await act(async () => await new Promise((r) => setTimeout(r, 0)));
}

function buttons(): string[] {
  return [...host.querySelectorAll('button')].map((b) => b.textContent ?? '');
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute('open');
  };
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function openPanel() {
  await act(async () =>
    root.render(
      <MemoryRouter initialEntries={['/console']}>
        <SirenPanel alert={ALERT} />
      </MemoryRouter>,
    ),
  );
  expect(host.textContent).toContain('Sirens 1/1 verified');
  const toggle = [...host.querySelectorAll('button')].find((b) => b.getAttribute('aria-expanded') === 'false')!;
  await act(async () => toggle.click());
  await flush();
}

describe('SirenPanel', () => {
  it('shows the tier and evidence, and no button when Cedar allows none (a judge)', async () => {
    mockApi({ test_siren: false, sound_siren: false, stop_siren: false });
    await openPanel();
    expect(host.textContent).toContain('3.1 A · +24 dB');
    expect(buttons().filter((b) => /Sound|Stop|Test|SMS/.test(b))).toEqual([]);
  });

  it('a Critical without a second officer says so (202)', async () => {
    const calls = mockApi(
      { test_siren: true, sound_siren: true, stop_siren: true },
      { request_id: 'req_1', needs_second_officer: true, expires_at: '2026-10-22T08:33:00Z' },
    );
    await openPanel();
    const labels = buttons();
    for (const b of ['Test silent', 'Test audible', 'Sound Warning', 'Sound Critical', 'Stop sirens']) expect(labels).toContain(b);
    const critical = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Sound Critical')!;
    await act(async () => critical.click());
    const confirm = [...host.querySelectorAll('dialog button')].find((b) => b.textContent === 'Sound Critical')!;
    await act(async () => confirm.click());
    await flush();
    expect(calls).toContain('POST /villages/thunag/sirens/sound');
    expect(host.querySelector('[role="status"]')?.textContent).toContain('Critical needs a second officer');
  });
});

describe('SirenLastTested', () => {
  it('renders the line, and nothing without a siren', async () => {
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/village/thunag']}>
          <SirenLastTested sirens={{ count: 1, sounding: 0, last_test_at: null, last_test_ok: null, overdue: false }} />
          <SirenLastTested sirens={null} />
        </MemoryRouter>,
      ),
    );
    const notes = host.querySelectorAll('[role="note"]');
    expect(notes).toHaveLength(1);
    expect(notes[0].className).toContain('bad-text');
  });
});
