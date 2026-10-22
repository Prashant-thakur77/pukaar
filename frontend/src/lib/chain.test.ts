import { describe, expect, it } from 'vitest';
import { custom, decodeFunctionData, encodeFunctionResult, erc20Abi } from 'viem';
import { explorerAddress, formatTinr, readPoolOnChain } from './chain';

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
