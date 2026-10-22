// Pukaar Raahat: read-only chain access from the browser (viem). No wallet, no signing: the page checks
// what the API says against the chain itself, through the chain's public RPC endpoint.
import { createPublicClient, erc20Abi, formatUnits, http, type Transport } from 'viem';
import type { Lang } from '../store';

export function explorerAddress(explorer: string | null | undefined, address: string): string | null {
  return explorer ? `${explorer}/address/${address}` : null;
}

export function explorerTx(explorer: string | null | undefined, hash: string): string | null {
  return explorer ? `${explorer}/tx/${hash}` : null;
}

/** Whole tINR (18 decimals) with Indian grouping and at most 2 decimals, exact for any amount. */
export function formatTinr(wei: string | bigint, lang: Lang): string {
  const units = formatUnits(BigInt(wei), 18);
  const nf = new Intl.NumberFormat(lang === 'hi' ? 'hi-IN' : 'en-IN', { maximumFractionDigits: 2 });
  // Intl formats a decimal string exactly (no Number conversion); the cast is for older lib typings.
  return nf.format(units as unknown as number);
}

/** The pool's tINR balance, read straight from the chain. Throws if the endpoint is on another chain. */
export async function readPoolOnChain(
  where: { chainId: number; token: string; pool: string },
  transport: Transport,
): Promise<bigint> {
  const client = createPublicClient({ transport });
  const got = await client.getChainId();
  if (got !== where.chainId) throw new Error(`RPC is on chain ${got}, expected ${where.chainId}`);
  return client.readContract({
    address: where.token as `0x${string}`,
    abi: erc20Abi,
    functionName: 'balanceOf',
    args: [where.pool as `0x${string}`],
  });
}

export function rpcTransport(url: string): Transport {
  return http(url, { timeout: 8_000, retryCount: 1 });
}
