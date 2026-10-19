import { NavLink, Outlet } from 'react-router-dom';
import { CalibrationBadge } from './components/CalibrationBadge';
import { DataStatus } from './components/DataStatus';

/** The shell: wordmark, route tabs, calibration badge and data status. */
export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <span className="wordmark">oap {'·'} explorer</span>
        <nav aria-label="Views">
          <NavLink to="/landscape" className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Landscape
          </NavLink>
        </nav>
        <div className="topbar__right">
          <CalibrationBadge />
          <DataStatus />
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
