import { useEffect, useState } from 'react';
import { API_BASE, useAppStore } from '../store';
import { CheckCircle2, Cpu, ServerCrash, UploadCloud, Waves } from 'lucide-react';

interface RuntimeStatus {
  is_online: boolean;
  llm: {
    enabled: boolean;
    reachable: boolean;
    base_url: string;
    model: string;
    detail: string;
  };
  hydromet: {
    enabled: boolean;
    reachable: boolean;
    detail: string;
  };
}

export default function Settings() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { syncStatus, fetchSyncStatus, flushQueue, queueCount } = useAppStore();
  const [isFlushing, setIsFlushing] = useState(false);

  useEffect(() => {
    const loadRuntime = async () => {
      try {
        const response = await fetch(`${API_BASE}/settings/runtime`);
        if (!response.ok) {
          throw new Error(await response.text());
        }
        setRuntime(await response.json());
      } catch (loadError) {
        console.error(loadError);
        setError('Could not load runtime status.');
      }
    };

    loadRuntime();
    fetchSyncStatus();
    const interval = setInterval(fetchSyncStatus, 8000);
    return () => clearInterval(interval);
  }, [fetchSyncStatus]);

  const onFlush = async () => {
    setIsFlushing(true);
    try {
      await flushQueue();
      await fetchSyncStatus();
    } finally {
      setIsFlushing(false);
    }
  };

  return (
    <div className="space-y-6 pb-20">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">Runtime Status</h2>
        <p className="text-sm text-gray-500 mt-1">
          Model runtime and live hydromet enrichment.
        </p>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <UploadCloud className="w-5 h-5 text-blue-600" /> Sync status
          </h3>
          <button
            onClick={onFlush}
            disabled={isFlushing || queueCount === 0}
            className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {isFlushing ? 'Flushing...' : `Flush queue (${queueCount})`}
          </button>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3">
            <div className="text-xs uppercase tracking-wide text-yellow-700 font-semibold">Pending</div>
            <div className="mt-1 text-xl font-bold text-yellow-900">{syncStatus?.pending ?? 0}</div>
          </div>
          <div className="rounded-lg border border-green-200 bg-green-50 p-3">
            <div className="text-xs uppercase tracking-wide text-green-700 font-semibold">Sincronizado</div>
            <div className="mt-1 text-xl font-bold text-green-900">{syncStatus?.synced ?? 0}</div>
          </div>
          <div className="rounded-lg border border-red-200 bg-red-50 p-3">
            <div className="text-xs uppercase tracking-wide text-red-700 font-semibold">Failed</div>
            <div className="mt-1 text-xl font-bold text-red-900">{syncStatus?.failed ?? 0}</div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <Cpu className="w-5 h-5 text-blue-600" /> Model runtime
          </h3>
          {runtime ? (
            <div className="mt-4 space-y-3 text-sm text-gray-700">
              <div className="flex items-center gap-2">
                {runtime.llm.reachable ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <ServerCrash className="w-4 h-4 text-red-600" />}
                <span>{runtime.llm.reachable ? 'LLM endpoint reachable' : 'LLM endpoint not reachable'}</span>
              </div>
              <div><span className="text-gray-500">Enabled:</span> {runtime.llm.enabled ? 'Yes' : 'No'}</div>
              <div><span className="text-gray-500">Base URL:</span> {runtime.llm.base_url}</div>
              <div><span className="text-gray-500">Model:</span> {runtime.llm.model}</div>
              <div><span className="text-gray-500">Detail:</span> {runtime.llm.detail}</div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-gray-500">Loading runtime status...</p>
          )}
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <Waves className="w-5 h-5 text-cyan-600" /> Hydromet provider
          </h3>
          {runtime ? (
            <div className="mt-4 space-y-3 text-sm text-gray-700">
              <div className="flex items-center gap-2">
                {runtime.hydromet.reachable ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <ServerCrash className="w-4 h-4 text-red-600" />}
                <span>{runtime.hydromet.reachable ? 'Provider reachable' : 'Provider not reachable'}</span>
              </div>
              <div><span className="text-gray-500">Enabled:</span> {runtime.hydromet.enabled ? 'Yes' : 'No'}</div>
              <div><span className="text-gray-500">Detail:</span> {runtime.hydromet.detail}</div>
              <div><span className="text-gray-500">Backend connectivity toggle:</span> {runtime.is_online ? 'Online' : 'Offline'}</div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-gray-500">Loading provider status...</p>
          )}
        </div>
      </section>
    </div>
  );
}
