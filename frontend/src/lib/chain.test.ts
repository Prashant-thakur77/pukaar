import { describe, expect, it } from 'vitest';
import { custom, decodeFunctionData, encodeFunctionResult, erc20Abi, keccak256, toBytes } from 'viem';
import {
  ALERT_REGISTRY_ABI,
  alertKey,
  explorerAddress,
  explorerTx,
  formatTinr,
  readAnchor,
  readPoolOnChain,
  verifyCapHash,
} from './chain';
import capFixture from './fixtures/cap-alert.xml?raw';

const TOKEN = '0x5FbDB2315678afecb367f032d93F642f64180aa3';
const POOL = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266';

/** A scripted JSON-RPC endpoint: eth_chainId and the ERC-20 balanceOf the page reads. */
function scripted(chainId: number, balance: bigint) {
  const calls: string[] = [];
  const transport = custom({
    async request({ method, params }: { method: string; params?: unknown }) {
      calls.push(method);
      if (method === 'eth_chainId') return `0x${chainId.toString(16)}`;
      if (method === 'eth_call') {
        const [tx] = params as [{ to: string; data: `0x${string}` }];
        expect(tx.to.toLowerCase()).toBe(TOKEN.toLowerCase());
        const { functionName, args } = decodeFunctionData({ abi: erc20Abi, data: tx.data });
        expect(functionName).toBe('balanceOf');
        expect((args?.[0] as string).toLowerCase()).toBe(POOL.toLowerCase());
        return encodeFunctionResult({ abi: erc20Abi, functionName: 'balanceOf', result: balance });
      }
      throw new Error(`unexpected ${method}`);
    },
  });
  return { transport, calls };
}

describe('raahat chain helpers', () => {
  it('links an address to the chain explorer, or nothing on a local chain', () => {
    expect(explorerAddress('https://sepolia.basescan.org', POOL)).toBe(`https://sepolia.basescan.org/address/${POOL}`);
    expect(explorerAddress(null, POOL)).toBeNull();
  });

  it('formats tINR from exact wei with Indian grouping, no float drift', () => {
    expect(formatTinr('500000000000000000000000', 'en')).toBe('5,00,000');
    expect(formatTinr(1_500_250_000_000_000_000_000n, 'en')).toBe('1,500.25');
    // 10^30 wei: far past Number.MAX_SAFE_INTEGER as wei, still exact.
    expect(formatTinr('1000000000000000000000000000000', 'en')).toBe('10,00,00,00,00,000');
    expect(formatTinr('0', 'hi')).toBe('0');
  });

  it('reads the pool balance in the browser, straight from the chain', async () => {
    const { transport } = scripted(31337, 7n * 10n ** 18n);
    const got = await readPoolOnChain({ chainId: 31337, token: TOKEN, pool: POOL }, transport);
    expect(got).toBe(7n * 10n ** 18n);
  });

  it('refuses to read from an endpoint on another chain', async () => {
    const { transport, calls } = scripted(1, 1n);
    await expect(readPoolOnChain({ chainId: 84532, token: TOKEN, pool: POOL }, transport)).rejects.toThrow(/chain 1/);
    expect(calls).toEqual(['eth_chainId']);
  });
});

// keccak256 of fixtures/cap-alert.xml, computed separately with Python's eth_utils.keccak over the file's bytes.
const FIXTURE_HASH = '0x65b9ee904cda9c8cdcc70e4a36c6ecfc425ca4a467c6042f0c684b5f58f221b0';
const REGISTRY = '0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512';

function serve(body: string, status = 200) {
  const urls: string[] = [];
  const fetcher = async (url: string) => {
    urls.push(url);
    return new Response(body, { status });
  };
  return { fetcher, urls };
}

describe('re-verify a CAP anchor in the browser', () => {
  it('hashes the served CAP bytes exactly as the backend did (UTF-8, Hindi included)', async () => {
    const { fetcher, urls } = serve(capFixture);
    const got = await verifyCapHash('https://api.example/cap/alerts/alr_fixture.xml', FIXTURE_HASH, fetcher);
    expect(got).toEqual({ ok: true, computed: FIXTURE_HASH });
    expect(urls).toEqual(['https://api.example/cap/alerts/alr_fixture.xml']);
  });

  it('a changed document does not match', async () => {
    const { fetcher } = serve(capFixture.replace('Exercise', 'Actual'));
    const got = await verifyCapHash('https://api.example/x.xml', FIXTURE_HASH, fetcher);
    expect(got.ok).toBe(false);
    expect(got.computed).not.toBe(FIXTURE_HASH);
  });

  it('compares hashes without caring about hex case', async () => {
    const { fetcher } = serve(capFixture);
    expect((await verifyCapHash('u', FIXTURE_HASH.toUpperCase().replace('0X', '0x'), fetcher)).ok).toBe(true);
  });

  it('a feed that is not reachable is an error, never a match', async () => {
    const { fetcher } = serve('not found', 404);
    await expect(verifyCapHash('u', FIXTURE_HASH, fetcher)).rejects.toThrow(/404/);
  });

  it('alert keys are keccak256 of the alert id, as the backend anchors them', () => {
    expect(alertKey('alr_01J9')).toBe(keccak256(toBytes('alr_01J9')));
  });

  it('reads the anchored record from the registry', async () => {
    const key = alertKey('alr_fixture');
    const transport = custom({
      async request({ method, params }: { method: string; params?: unknown }) {
        if (method === 'eth_chainId') return '0x7a69';
        if (method === 'eth_call') {
          const [tx] = params as [{ to: string; data: `0x${string}` }];
          expect(tx.to.toLowerCase()).toBe(REGISTRY.toLowerCase());
          const { functionName, args } = decodeFunctionData({ abi: ALERT_REGISTRY_ABI, data: tx.data });
          expect(functionName).toBe('get');
          expect(args?.[0]).toBe(key);
          return encodeFunctionResult({
            abi: ALERT_REGISTRY_ABI,
            functionName: 'get',
            result: {
              villageId: keccak256(toBytes('thunag')),
              level: 2,
              capHash: FIXTURE_HASH,
              capUri: 'https://api.example/cap/alerts/alr_fixture.xml',
              issuedAt: 1688862600n,
              exercise: true,
              delivered: 12,
              acknowledged: 9,
              afterActionHash: `0x${'00'.repeat(32)}`,
            },
          });
        }
        throw new Error(`unexpected ${method}`);
      },
    });
    const rec = await readAnchor({ chainId: 31337, registry: REGISTRY, alertKey: key }, transport);
    expect(rec).toMatchObject({ level: 2, capHash: FIXTURE_HASH, exercise: true, delivered: 12, acknowledged: 9 });
  });

  it('links a transaction to the explorer', () => {
    expect(explorerTx('https://sepolia.basescan.org', '0xabc')).toBe('https://sepolia.basescan.org/tx/0xabc');
    expect(explorerTx(null, '0xabc')).toBeNull();
  });
});
