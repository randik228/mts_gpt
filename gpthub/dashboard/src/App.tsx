import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import TaskChainBuilder from "./pages/TaskChainBuilder";
import MemoryViewer from "./pages/MemoryViewer";
import RoutingAnalytics from "./pages/RoutingAnalytics";
import ModelCatalog from "./pages/ModelCatalog";
import "./app.css";

export default function App() {
  return (
    <BrowserRouter>
      <header className="header">
        <a href="/" className="logo">
          <div className="logo-mark">G</div>
          <span className="logo-text">GPTHub</span>
          <span className="logo-badge">MTS</span>
        </a>

        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <i className="nav-icon">🔗</i> Task Chain
          </NavLink>
          <NavLink to="/memory" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <i className="nav-icon">🧠</i> Memory
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <i className="nav-icon">📊</i> Analytics
          </NavLink>
          <NavLink to="/models" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <i className="nav-icon">🤖</i> Models
          </NavLink>
        </nav>

        <div className="header-right">
          <div className="status-dot" title="Proxy online" />
          <span className="status-text">proxy:8000</span>
        </div>
      </header>

      <main className="main">
        <Routes>
          <Route path="/" element={<TaskChainBuilder />} />
          <Route path="/memory" element={<MemoryViewer />} />
          <Route path="/analytics" element={<RoutingAnalytics />} />
          <Route path="/models" element={<ModelCatalog />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
