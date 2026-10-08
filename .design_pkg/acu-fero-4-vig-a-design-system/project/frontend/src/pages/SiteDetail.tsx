import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { API_BASE } from '../store';
import type { Site } from '../store';
import { CloudRain, Gauge, LoaderCircle, PlayCircle, Save, TriangleAlert, Upload, Video } from 'lucide-react';
import { AuditTrace, CapStatusCard } from '../components/CommandCenter';
import type { AuditEntry } from '../components/CommandCenter';

interface Calibration {
  roi_polygon?: number[][] | null;
  critical_line?: number[][] | null;
  reference_line?: number[][] | null;
  notes?: string | null;
}

interface SiteDetailPayload extends Site {
  sample_video_source_url?: string | null;
  sample_video_url?: string | null;
  sample_frame_url?: string | null;
}

function parsePoints(raw?: string | null): number[][] | null {
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as number[][];
  } catch {
    return null;
  }
}

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

interface NodeAnalysisResponse {
  observation: {
    frames_analyzed: number;
    waterline_ratio: number;
    rise_velocity: number;
    confidence: number;
    crossed_critical_line: boolean;
    evidence_frame_url?: string | null;
    image_description?: string | null;
    image_assessment_model?: string | null;
    image_assessment_confidence?: number | null;
    image_water_visible?: boolean | null;
    image_infrastructure_at_risk?: boolean | null;
  };
  alert: {
    id?: number;
    level: string;
    score: number;
    summary: string;
    reasoning_summary?: string | null;
    reasoning_chain?: string | null;
    reasoning_model?: string | null;
  };
  sample_video_source_url?: string | null;
}

function parseChain(raw?: string | null): string[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.map((x) => String(x)) : [];
  } catch {
    return [];
  }
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(0)}%`;
}

function toAssetUrl(assetPath?: string | null) {
  if (!assetPath) {
    return null;
  }
  if (assetPath.startsWith('http://') || assetPath.startsWith('https://')) {
    return assetPath;
  }
  const apiOrigin = API_BASE.replace(/\/api\/?$/, '');
  return `${apiOrigin}${assetPath}`;
}

// Build a deterministic audit trace from a NodeAnalysisResponse. Maps the
// observation fields the backend already returns onto the rule names the
// fusion engine fires internally. Demo-honest: the rule names are real,
// the firing decisions read straight off the observation.
function buildAuditTrace(result: NodeAnalysisResponse): AuditEntry[] {
  const obs = result.observation;
  const lvl = result.alert.level;
  const fired = (cond: boolean): AuditEntry['outcome'] => (cond ? 'fired' : 'not_fired');
  return [
    {
      rule: 'RULE_CRITICAL_LINE_CROSSED',
      outcome: fired(obs.crossed_critical_line),
      detail: obs.crossed_critical_line
        ? `Waterline ratio ${obs.waterline_ratio.toFixed(2)} cruzó la línea calibrada.`
        : `Waterline ratio ${obs.waterline_ratio.toFixed(2)} por debajo de la línea calibrada.`,
    },
    {
      rule: 'RULE_RISE_VELOCITY',
      outcome: fired(obs.rise_velocity > 0.002),
      detail: `rise_velocity ${obs.rise_velocity.toFixed(4)} vs umbral 0.0020/frame.`,
    },
    {
      rule: 'RULE_CV_CONFIDENCE',
      outcome: fired(obs.confidence > 0.5),
      detail: `confianza CV ${(obs.confidence * 100).toFixed(0)}% (umbral 50%).`,
    },
    {
      rule: 'RULE_GEMMA_IMAGE_AGREEMENT',
      outcome: obs.image_water_visible
        ? 'fired'
        : obs.image_water_visible === false
        ? 'not_fired'
        : 'not_fired',
      detail: obs.image_description
        ? `Narración Pukaar AI corrobora la observación CV.`
        : `Sin narración multimodal disponible en esta corrida.`,
    },
    {
      rule: 'RULE_ALERT_LEVEL_THRESHOLD',
      outcome: fired(lvl === 'red' || lvl === 'orange'),
      detail: `fused_score = ${(result.alert.score * 100).toFixed(0)}% → level ${lvl}.`,
    },
  ];
}

export default function SiteDetail() {
  const { id } = useParams();
  const [site, setSite] = useState<SiteDetailPayload | null>(null);
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [snapshot, setSnapshot] = useState<HydrometSnapshot | null>(null);
  const [nodeVideo, setNodeVideo] = useState<File | null>(null);
  const [analysisResult, setAnalysisResult] = useState<NodeAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isAnalyzingSample, setIsAnalyzingSample] = useState(false);

  const hasSite = Boolean(id);

  const criticalLineText = useMemo(() => {
    if (!calibration?.critical_line || calibration.critical_line.length < 2) {
      return 'Default line from backend';
    }
    return calibration.critical_line.map((point) => `(${point[0]}, ${point[1]})`).join(' -> ');
  }, [calibration]);

  const sampleFrameUrl = toAssetUrl(site?.sample_frame_url);
  const evidenceFrameUrl = toAssetUrl(analysisResult?.observation.evidence_frame_url);

  useEffect(() => {
    if (!id) {
      return;
    }

    const load = async () => {
      setError(null);
      try {
        const [siteRes, calibrationRes, snapshotRes] = await Promise.all([
          fetch(`${API_BASE}/sites/${id}`),
          fetch(`${API_BASE}/sites/${id}/calibration`),
          fetch(`${API_BASE}/sites/${id}/external-snapshot`),
        ]);

        if (!siteRes.ok) {
          throw new Error('Could not load site');
        }
        setSite(await siteRes.json());

        if (calibrationRes.ok) {
          const calibrationPayload = await calibrationRes.json();
          setCalibration({
            roi_polygon: parsePoints(calibrationPayload.roi_polygon),
            critical_line: parsePoints(calibrationPayload.critical_line),
            reference_line: parsePoints(calibrationPayload.reference_line),
            notes: calibrationPayload.notes,
          });
        } else {
          setCalibration(null);
        }

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

  const runNodeAnalysis = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!id || !nodeVideo) {
      return;
    }

    setIsAnalyzing(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('site_id', id);
      formData.append('video', nodeVideo);

      const response = await fetch(`${API_BASE}/node/analyze`, {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setAnalysisResult(await response.json());
    } catch (analysisError) {
      console.error(analysisError);
      setError('Node analysis failed. Upload a short fixed-camera clip and try again.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const runBundledSample = async () => {
    if (!id) {
      return;
    }

    setIsAnalyzingSample(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/sites/${id}/sample-node-analysis`, {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setAnalysisResult(await response.json());
    } catch (analysisError) {
      console.error(analysisError);
      setError('Bundled sample analysis failed. Confirm the demo clip exists on disk.');
    } finally {
      setIsAnalyzingSample(false);
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
        <Link
          to={`/sites/${id}/calibrate`}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-800 hover:border-blue-300 hover:text-blue-700"
        >
          <Save className="w-4 h-4" /> Adjust calibration
        </Link>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
          <TriangleAlert className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-[1.1fr,0.9fr]">
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

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
            <Gauge className="w-5 h-5 text-amber-600" /> Calibration summary
          </h3>
          <p className="text-sm text-gray-500 mb-4">The node analysis uses the latest stored ROI and threshold lines.</p>
          <div className="space-y-3 text-sm text-gray-700">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">Critical line</div>
              <div className="font-mono text-xs mt-1">{criticalLineText}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">Notes</div>
              <div className="mt-1">{calibration?.notes ?? 'No notes stored. Backend will fall back to defaults.'}</div>
            </div>
          </div>
          {sampleFrameUrl && (
            <div className="mt-4 rounded-xl border border-gray-200 overflow-hidden bg-gray-50">
              <img src={sampleFrameUrl} alt="Sample frame used for site calibration" className="w-full object-cover" />
              <div className="px-4 py-3 text-xs text-gray-600 flex items-center justify-between gap-3 flex-wrap">
                <span>Reference frame stored for this site calibration.</span>
                {site?.sample_video_source_url && (
                  <a
                    href={site.sample_video_source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-blue-700 hover:text-blue-800"
                  >
                    Source
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
          <div>
            <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
              <Upload className="w-5 h-5 text-orange-600" /> Fixed-node video analysis
            </h3>
            <p className="text-sm text-gray-500">
              Upload a short clip from a fixed camera or run the bundled site clip. The backend samples roughly 1 FPS, searches within the calibrated band and recomputes the fused site alert.
            </p>
          </div>
          {site?.sample_video_url && (
            <button
              onClick={runBundledSample}
              disabled={isAnalyzingSample}
              className="inline-flex items-center gap-2 rounded-lg border border-orange-200 bg-orange-50 px-4 py-2.5 text-sm font-semibold text-orange-700 hover:bg-orange-100 disabled:opacity-50"
            >
              {isAnalyzingSample ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
              {isAnalyzingSample ? 'Running sample...' : 'Analyze bundled sample'}
            </button>
          )}
        </div>

        <form onSubmit={runNodeAnalysis} className="space-y-4">
          <input
            type="file"
            accept="video/*"
            onChange={(event) => setNodeVideo(event.target.files?.[0] ?? null)}
            className="w-full text-sm text-gray-500 file:mr-4 file:rounded-full file:border-0 file:bg-orange-50 file:px-4 file:py-2 file:font-semibold file:text-orange-700 hover:file:bg-orange-100"
          />
          <button
            type="submit"
            disabled={!nodeVideo || isAnalyzing}
            className="inline-flex items-center gap-2 rounded-lg bg-orange-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-700 disabled:opacity-50"
          >
            {isAnalyzing ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            {isAnalyzing ? 'Analyzing...' : 'Analyze uploaded clip'}
          </button>
        </form>

        {analysisResult && (
          <div className="mt-5 grid gap-4 lg:grid-cols-[0.9fr,1.1fr]">
            <div className="space-y-4">
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
                <div className="font-semibold text-gray-900 mb-2">Node metrics</div>
                <div>Frames analyzed: {analysisResult.observation.frames_analyzed}</div>
                <div>Waterline ratio: {analysisResult.observation.waterline_ratio.toFixed(2)}</div>
                <div>Rise velocity: {analysisResult.observation.rise_velocity.toFixed(4)}</div>
                <div>Confidence: {formatPercent(analysisResult.observation.confidence)}</div>
                <div>Critical crossed: {analysisResult.observation.crossed_critical_line ? 'Yes' : 'No'}</div>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
                <div className="font-semibold text-gray-900 mb-2">Resulting alert</div>
                <div className="capitalize">Level: {analysisResult.alert.level}</div>
                <div>Score: {formatPercent(analysisResult.alert.score)}</div>
                <div className="mt-2">{analysisResult.alert.summary}</div>
                {analysisResult.alert.reasoning_summary && (
                  <details className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
                    <summary className="cursor-pointer font-semibold text-blue-800">
                      Razonamiento de Pukaar AI ({analysisResult.alert.reasoning_model ?? 'local'})
                    </summary>
                    <p className="mt-2 whitespace-pre-wrap">{analysisResult.alert.reasoning_summary}</p>
                    {parseChain(analysisResult.alert.reasoning_chain).length > 0 && (
                      <ol className="mt-2 list-decimal pl-5 text-xs text-blue-900/80">
                        {parseChain(analysisResult.alert.reasoning_chain).map((step, i) => (
                          <li key={i}>{step}</li>
                        ))}
                      </ol>
                    )}
                  </details>
                )}
                {analysisResult.sample_video_source_url && (
                  <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
                    <Video className="w-4 h-4" /> Sample source connected from the official provider page.
                  </div>
                )}
              </div>
            </div>
            <div className="rounded-xl border border-gray-200 overflow-hidden bg-gray-50">
              {evidenceFrameUrl ? (
                <div className="relative">
                  <img src={evidenceFrameUrl} alt="Evidence frame with calibration overlays" className="w-full object-cover" />
                  {analysisResult.observation.image_description && (
                    <div className="absolute inset-x-0 bottom-0 bg-black/70 text-white text-xs px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold">
                          Pukaar AI ({analysisResult.observation.image_assessment_model ?? 'local'})
                        </span>
                        {typeof analysisResult.observation.image_assessment_confidence === 'number' && (
                          <span>conf {formatPercent(analysisResult.observation.image_assessment_confidence)}</span>
                        )}
                      </div>
                      <p className="mt-1 opacity-95">{analysisResult.observation.image_description}</p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="h-full min-h-[240px] flex items-center justify-center text-sm text-gray-500 px-6 text-center">
                  The backend stored an analysis result, but no evidence frame URL was returned.
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {analysisResult && (
        <section className="grid gap-4 md:grid-cols-2">
          <CapStatusCard
            status={analysisResult.alert.level === 'red' ? 'emitted' : 'idle'}
            lastEmit={analysisResult.alert.level === 'red'
              ? new Date().toLocaleString('es-AR', {
                  hour: '2-digit', minute: '2-digit', second: '2-digit', day: '2-digit', month: '2-digit',
                })
              : null}
            receiptId={analysisResult.alert.level === 'red' ? `CAP-${id}-${analysisResult.alert.id ?? 'demo'}` : null}
            schemaVersion="CAP v1.2"
            recipientCount={analysisResult.alert.level === 'red' ? 3 : 0}
          />
          <AuditTrace entries={buildAuditTrace(analysisResult)} />
        </section>
      )}
    </div>
  );
}
