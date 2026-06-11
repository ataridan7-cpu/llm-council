import { useNavigate } from 'react-router-dom';
import './NotFound.css';

export default function NotFound() {
  const navigate = useNavigate();
  return (
    <div className="not-found">
      <div className="nf-code">404</div>
      <h1>Page not found</h1>
      <p>The page you're looking for doesn't exist.</p>
      <div className="nf-actions">
        <button className="nf-btn primary" onClick={() => navigate('/')}>Go to Dashboard</button>
        <button className="nf-btn" onClick={() => navigate(-1)}>Go back</button>
      </div>
    </div>
  );
}
