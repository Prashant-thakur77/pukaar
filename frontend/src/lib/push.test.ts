import { describe, expect, it } from 'vitest';
import { isIOS, pushEnvironment, sameKey, subscriptionId, urlBase64ToUint8Array } from './push';

const all = { hasServiceWorker: true, hasPushManager: true, hasNotification: true, standalone: false };
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36';
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1';
const IPAD_DESKTOP = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15';

describe('push environment', () => {
  it('Android Chrome is supported', () => {
    expect(pushEnvironment({ ...all, userAgent: ANDROID })).toBe('supported');
  });

  it('iPhone and iPad need the app on the Home Screen first', () => {
    expect(pushEnvironment({ ...all, hasPushManager: false, userAgent: IPHONE })).toBe('ios-install');
    expect(isIOS({ userAgent: IPAD_DESKTOP, platform: 'MacIntel', maxTouchPoints: 5 })).toBe(true);
    expect(isIOS({ userAgent: IPAD_DESKTOP, platform: 'MacIntel', maxTouchPoints: 0 })).toBe(false);
    expect(pushEnvironment({ ...all, standalone: true, userAgent: IPHONE })).toBe('supported');
  });

  it('a browser without the APIs is unsupported', () => {
    expect(pushEnvironment({ ...all, hasPushManager: false, userAgent: ANDROID })).toBe('unsupported');
    expect(pushEnvironment({ ...all, hasServiceWorker: false, userAgent: ANDROID })).toBe('unsupported');
  });
});

describe('keys and ids', () => {
  const KEY = 'BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8';

  it('decodes the base64url VAPID key to the 65-byte point', () => {
    const b = urlBase64ToUint8Array(KEY);
    expect(b.length).toBe(65);
    expect(b[0]).toBe(4);
  });

  it('notices a subscription made with another server key', () => {
    const same = urlBase64ToUint8Array(KEY).buffer;
    expect(sameKey(same, KEY)).toBe(true);
    const other = new Uint8Array(65);
    other[0] = 4;
    expect(sameKey(other.buffer, KEY)).toBe(false);
    expect(sameKey(null, KEY)).toBe(false);
  });

  it('computes the same subscription id as the server', async () => {
    // backend/tests/test_push.py: test_subscription_id_matches_the_web_app
    expect(await subscriptionId('https://fcm.googleapis.com/fcm/send/abc')).toBe('4e9bdab8bbe7189c00aebb09');
  });
});
