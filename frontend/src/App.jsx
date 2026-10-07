import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom';
import AttentionPage from './pages/AttentionPage.jsx';
import ExceptionsPage from './pages/ExceptionsPage.jsx';
import ExceptionDetailPage from './pages/ExceptionDetailPage.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import LogExceptionPage from './pages/LogExceptionPage.jsx';
import StagingCheckPage from './pages/StagingCheckPage.jsx';

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-inner">
          <Link className="brand" to="/exceptions">
            <img className="brand-logo" src="/Saia_ltl.png" alt="Saia LTL Freight" />
            <span className="brand-text">
              <strong>RootIQ</strong>
              <small>OV Exception · AI Root Cause &amp; Prevention</small>
            </span>
          </Link>
          <nav className="app-nav">
            <NavLink to="/exceptions">OV Exceptions</NavLink>
            <NavLink to="/log">Log exception</NavLink>
            <NavLink to="/staging-check">Staging check</NavLink>
            <NavLink to="/dashboard">Root Cause Dashboard</NavLink>
            <NavLink to="/attention">Attention &amp; Training</NavLink>
          </nav>
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/exceptions" replace />} />
          <Route path="/exceptions" element={<ExceptionsPage />} />
          <Route path="/exceptions/:id" element={<ExceptionDetailPage />} />
          <Route path="/log" element={<LogExceptionPage />} />
          <Route path="/staging-check" element={<StagingCheckPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/attention" element={<AttentionPage />} />
        </Routes>
      </main>

      <footer className="app-footer">
        <span>Saia LTL Freight · OS&amp;D Operations</span>
        <span>RootIQ proof of concept — AI output is advisory and should be reviewed by an analyst.</span>
      </footer>
    </div>
  );
}
