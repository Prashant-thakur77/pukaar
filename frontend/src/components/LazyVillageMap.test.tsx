import { afterEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { LazyVillageMap } from './LazyVillageMap';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLDivElement | null = null;
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
});

describe('LazyVillageMap', () => {
  it('waits behind a "Show map" button and does not load the map on its own', () => {
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    act(() =>
      root!.render(
        <MemoryRouter>
          <LazyVillageMap villages={[]} />
        </MemoryRouter>,
      ),
    );
    const btn = host.querySelector('.map-gate button');
    expect(btn?.textContent).toMatch(/नक्शा दिखाएँ|Show map/);
    // No IntersectionObserver in jsdom: nothing loads until the button is tapped.
    expect(host.querySelector('.map')).toBeNull();
  });
});
