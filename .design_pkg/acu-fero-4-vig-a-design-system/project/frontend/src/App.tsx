import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Report from './pages/Report';
import Queue from './pages/Queue';
import Calibration from './pages/Calibration';
import SiteDetail from './pages/SiteDetail';
import Settings from './pages/Settings';
import './index.css'; // ensure tailwind is imported here or in main.tsx

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="report" element={<Report />} />
          <Route path="queue" element={<Queue />} />
          <Route path="sites/:id" element={<SiteDetail />} />
          <Route path="sites/:id/calibrate" element={<Calibration />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
