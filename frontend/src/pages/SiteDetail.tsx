import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { API_BASE, type Site } from '../store';
import { CloudRain, TriangleAlert } from 'lucide-react';

interface HydrometSnapshot {
  site_id: string;
  signal_score: number;
  summary: string;
  precipitation_mm: number;
  precipitation_probability: number;
  river_discharge?: number | null;
  river_discharge_max?: number | null;
  river_discharge_trend?: number | null;
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(0)}%`;
}

export default function SiteDetail() {
  const { id } = useParams();
  const [site, setSite] = useState<Site | null>(null);
  const [snapshot, setSnapshot] = useState<HydrometSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const hasSite = Boolean(id);

  useEffect(() => {
    if (!id) {
      return;
    }

    const load = async () => {
      setError(null);
      try {
        const [siteRes, snapshotRes] = await Promise.all([
          fetch(`${API_BASE}/sites/${id}`),
          fetch(`${API_BASE}/sites/${id}/external-snapshot`),
        ]);

        if (!siteRes.ok) {
          throw new Error('Could not load site');
        }
        setSite(await siteRes.json());

        if (snapshotRes.ok) {
          setSnapshot(await snapshotRes.json());
        } else {
          setSnapshot(null);
        }
      } catch (loadError) {
        console.error(loadError);
        setError('Failed to load site detail.');
      }
    };

    load();
  }, [id]);

  const refreshHydromet = async () => {
    if (!id) {
      return;
    }

    setIsRefreshing(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/sites/${id}/external-snapshot/refresh`, {
        method: 'POST',
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || 'Hydromet refresh failed');
      }
      setSnapshot(await response.json());
    } catch (refreshError) {
      console.error(refreshError);
      setError(refreshError instanceof Error ? refreshError.message : 'Hydromet refresh failed.');
    } finally {
      setIsRefreshing(false);
    }
  };

  if (!hasSite) {
    return <div className="p-6 text-gray-600">Missing site identifier.</div>;
  }

  return (
    <div className="space-y-6 pb-20">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{site?.name ?? id}</h2>
          <p className="text-gray-500 mt-1">{site?.region ?? 'Loading region...'}</p>
          {site?.description && <p className="text-sm text-gray-600 mt-2 max-w-2xl">{site.description}</p>}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
          <TriangleAlert className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      <section className="grid gap-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-4 mb-4">
            <div>
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <CloudRain className="w-5 h-5 text-blue-600" /> Live hydromet context
              </h3>
              <p className="text-sm text-gray-500 mt-1">Open-Meteo weather + flood snapshot for this site.</p>
            </div>
            <button
              onClick={refreshHydromet}
              disabled={isRefreshing}
              className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {isRefreshing ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>

          {snapshot ? (
            <div className="space-y-3 text-sm text-gray-700">
              <div className="rounded-lg bg-blue-50 p-3 border border-blue-100">
                <div className="text-xs uppercase tracking-wide text-blue-700 font-semibold">Signal score</div>
                <div className="mt-1 text-2xl font-bold text-blue-900">{formatPercent(snapshot.signal_score)}</div>
              </div>
              <div>{snapshot.summary}</div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-gray-50 p-3 border border-gray-100">
                  <div className="text-xs text-gray-500">Rain now</div>
                  <div className="font-semibold">{snapshot.precipitation_mm.toFixed(1)} mm</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3 border border-gray-100">
                  <div className="text-xs text-gray-500">12h rain probability</div>
                  <div className="font-semibold">{snapshot.precipitation_probability.toFixed(0)}%</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3 border border-gray-100 col-span-2">
                  <div className="text-xs text-gray-500">River discharge</div>
                  <div className="font-semibold">
                    {snapshot.river_discharge != null ? `${snapshot.river_discharge.toFixed(1)} m3/s` : 'Unavailable'}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">No stored snapshot yet. Refresh to fetch live hydromet data.</p>
          )}
        </div>
      </section>
    </div>
  );
}
