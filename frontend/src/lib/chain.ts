// Pukaar Raahat: read-only chain access from the browser (viem). No wallet, no signing: the page checks
// what the API says against the chain itself, through the chain's public RPC endpoint.
import { createPublicClient, erc20Abi, formatUnits, http, keccak256, parseAbi, toBytes, type Hex, type Transport } from 'viem';
import type { Lang } from '../store';

export { explorerAddress, explorerTx } from './chain-links';

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

export const ALERT_REGISTRY_ABI = parseAbi([
  'struct AlertRecord { bytes32 villageId; uint8 level; bytes32 capHash; string capUri; uint64 issuedAt; bool exercise; uint32 delivered; uint32 acknowledged; bytes32 afterActionHash; }',
  'function get(bytes32 alertId) view returns (AlertRecord)',
]);

/** The registry key of an alert: keccak256 of its id (raahat/anchor.py alert_key). */
export function alertKey(alertId: string): Hex {
  return keccak256(toBytes(alertId));
}

/** An alert's record as the AlertRegistry holds it, read straight from the chain. */
export async function readAnchor(where: { chainId: number; registry: string; alertKey: Hex }, transport: Transport) {
  const client = createPublicClient({ transport });
  const got = await client.getChainId();
  if (got !== where.chainId) throw new Error(`RPC is on chain ${got}, expected ${where.chainId}`);
  return client.readContract({
    address: where.registry as Hex,
    abi: ALERT_REGISTRY_ABI,
    functionName: 'get',
    args: [where.alertKey],
  });
}

type Fetcher = (url: string) => Promise<Response>;

/**
 * Fetch the CAP XML at `uri` and keccak256 its exact bytes, as the backend did when it anchored the alert.
 * ok only when that equals the hash on chain; an unreachable feed throws (never reported as a match).
 */
export async function verifyCapHash(
  uri: string,
  onChainHash: string,
  fetcher: Fetcher = (u) => fetch(u, { cache: 'no-store' }),
): Promise<{ ok: boolean; computed: Hex }> {
  const res = await fetcher(uri);
  if (!res.ok) throw new Error(`CAP feed answered ${res.status}`);
  const computed = keccak256(new Uint8Array(await res.arrayBuffer()));
  return { ok: computed.toLowerCase() === onChainHash.toLowerCase(), computed };
}

/** When a transaction was mined (block number, unix seconds, and whether it reverted), or null while pending. */
export async function txMined(
  hash: string,
  transport: Transport,
): Promise<{ block: bigint; at: number; reverted: boolean } | null> {
  const client = createPublicClient({ transport });
  try {
    const receipt = await client.getTransactionReceipt({ hash: hash as Hex });
    const block = await client.getBlock({ blockNumber: receipt.blockNumber });
    return { block: receipt.blockNumber, at: Number(block.timestamp), reverted: receipt.status !== 'success' };
  } catch (err) {
    if ((err as Error)?.name === 'TransactionReceiptNotFoundError') return null;
    throw err;
  }
}
