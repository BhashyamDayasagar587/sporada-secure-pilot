import { Route, Routes, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Monitor from "./pages/Monitor";
import LiveView from "./pages/LiveView";
import Stream from "./pages/Stream";
import Config from "./pages/Config";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/monitor" replace />} />
        <Route path="/monitor" element={<Monitor />} />
        <Route path="/live" element={<LiveView />} />
        <Route path="/stream" element={<Stream />} />
        <Route path="/config" element={<Navigate to="/config/cameras" replace />} />
        <Route path="/config/cameras" element={<Config tab="cameras" />} />
        <Route path="/config/zones" element={<Config tab="zones" />} />
        <Route path="/config/zones/:cameraId" element={<Config tab="zones" />} />
        <Route path="/config/settings" element={<Config tab="settings" />} />
        {/* legacy paths → new homes */}
        <Route path="/overview" element={<Navigate to="/monitor" replace />} />
        <Route path="/cameras" element={<Navigate to="/config/cameras" replace />} />
        <Route path="/zones" element={<Navigate to="/config/zones" replace />} />
        <Route path="/settings" element={<Navigate to="/config/settings" replace />} />
      </Routes>
    </Layout>
  );
}
