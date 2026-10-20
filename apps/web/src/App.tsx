import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { CalibrationBadge } from './components/CalibrationBadge';
import { DataStatus } from './components/DataStatus';

/** The shell: wordmark, route tabs, calibration badge and data status. */
export default function App() {
  const { pathname } = useLocation();
  return (
    <div className="shell">
      <header className="topbar">
        <span className="wordmark">oap {'·'} explorer</span>
        <nav aria-label="Views">
          <NavLink to="/landscape" className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Landscape
          </NavLink>
          <NavLink to="/spreads" className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Spreads
          </NavLink>
          <NavLink to="/structures" className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Structures
          </NavLink>
          <NavLink to="/outcomes" className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Outcome map
          </NavLink>
        </nav>
        <div className="topbar__right">
          {/* The spreads page shows the full out-of-sample line itself. */}
          {pathname.startsWith('/spreads') ? null : <CalibrationBadge />}
          <DataStatus />
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
