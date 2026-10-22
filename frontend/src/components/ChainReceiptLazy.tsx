import { lazy, Suspense } from 'react';

// viem and the receipt card load only when an alert is opened, never with the console or village page.
const ChainReceipt = lazy(() => import('./ChainReceipt'));

export function ChainReceiptLazy({ alertId }: { alertId: string }) {
  return (
    <Suspense fallback={null}>
      <ChainReceipt alertId={alertId} />
    </Suspense>
  );
}
