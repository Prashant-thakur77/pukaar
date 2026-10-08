import { Outlet, Link, useLocation } from 'react-router-dom';
import { useAppStore, API_BASE } from '../store';
import { Activity, FileText, UploadCloud, Wifi, WifiOff, Settings, Siren, CheckCircle2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

export default function Layout() {
  const { isOnline, queueCount, checkConnectivity, setOnline } = useAppStore();
  const location = useLocation();
  const wasOffline = useRef(false);
  const prevQueue = useRef(queueCount);
  const [flashSynced, setFlashSynced] = useState(false);

  useEffect(() => {
    if (!isOnline) {
      wasOffline.current = true;
    } else if (wasOffline.current && queueCount === 0 && prevQueue.current > 0) {
      setFlashSynced(true);
      const t = setTimeout(() => setFlashSynced(false), 2500);
      wasOffline.current = false;
      return () => clearTimeout(t);
    }
    prevQueue.current = queueCount;
  }, [isOnline, queueCount]);

  useEffect(() => {
    checkConnectivity();
    const interval = setInterval(() => {
      checkConnectivity();
    }, 10000);
    return () => clearInterval(interval);
  }, [checkConnectivity]);

  const toggleOffline = async () => {
    const nextStatus = !isOnline;
    try {
      await fetch(`${API_BASE}/settings/connectivity`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_online: nextStatus }),
      });
    } catch (error) {
      console.error('Could not toggle backend offline status', error);
    }
    setOnline(nextStatus);
  };

  const navItems = [
    { path: '/', label: 'Comando', icon: <Activity className="w-5 h-5" /> },
    { path: '/report', label: 'Reporte', icon: <FileText className="w-5 h-5" /> },
    { path: '/queue', label: `Cola (${queueCount})`, icon: <UploadCloud className="w-5 h-5" /> },
    { path: '/settings', label: 'Runtime', icon: <Settings className="w-5 h-5" /> },
  ];

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 flex flex-col font-sans">
      <header className="bg-blue-600 text-white p-4 shadow-md flex justify-between items-center gap-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Activity className="w-6 h-6" /> Pukaar
        </h1>

        <button
          onClick={toggleOffline}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
            isOnline ? 'bg-green-500 hover:bg-green-400' : 'bg-red-500 hover:bg-red-400'
          }`}
        >
          {isOnline ? (
            <><Wifi className="w-4 h-4" /> Online</>
          ) : (
            <><WifiOff className="w-4 h-4" /> Offline</>
          )}
        </button>
      </header>

      {!isOnline && (
        <div className="bg-red-600 text-white px-4 py-2 text-sm font-semibold flex items-center justify-center gap-2 animate-pulse">
          <Siren className="w-4 h-4" />
          SIN CONECTIVIDAD — operación local activa · cola: {queueCount}
        </div>
      )}
      {flashSynced && (
        <div className="bg-green-600 text-white px-4 py-2 text-sm font-semibold flex items-center justify-center gap-2">
          <CheckCircle2 className="w-4 h-4" /> Sincronizado
        </div>
      )}
      <main className="flex-1 p-4 max-w-5xl mx-auto w-full">
        <Outlet />
      </main>

      <nav className="bg-white border-t border-gray-200 flex justify-around p-3 pb-safe fixed bottom-0 w-full md:relative">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex flex-col items-center gap-1 p-2 rounded-lg transition-colors ${
                isActive ? 'text-blue-600 bg-blue-50' : 'text-gray-500 hover:text-blue-500 hover:bg-gray-50'
              }`}
            >
              {item.icon}
              <span className="text-xs font-medium">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
