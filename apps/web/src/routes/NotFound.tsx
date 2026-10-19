import { Link } from 'react-router-dom';
import { EmptyState } from '../components/EmptyState';

export default function NotFound() {
  return (
    <div className="page">
      <EmptyState title="Page not found" hint="The explorer has two views." />
      <p className="muted">
        <Link to="/landscape">Landscape</Link> {'·'} <Link to="/spreads">Spreads</Link>
      </p>
    </div>
  );
}
