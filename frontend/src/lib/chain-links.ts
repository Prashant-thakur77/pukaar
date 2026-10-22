// Explorer links for Raahat records. No viem here: pages that only link to the chain stay light.

export function explorerAddress(explorer: string | null | undefined, address: string): string | null {
  return explorer ? `${explorer}/address/${address}` : null;
}

export function explorerTx(explorer: string | null | undefined, hash: string): string | null {
  return explorer ? `${explorer}/tx/${hash}` : null;
}
