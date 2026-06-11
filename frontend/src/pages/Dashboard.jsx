import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import './Dashboard.css';

const VERDICT_COLOR = { buy: '#22a74f', hold: '#e6a817', sell: '#e53e3e' };

function Dashboard() {
  const [ticker, setTicker] = useState('');
  const [recentAnalyses, setRecentAnalyses] = useState([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api.listAnalyses().then(setRecentAnalyses).catch(console.error);
  }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (t) navigate(`/stock/${t}`);
  };

  return (
    <div className="dashboard">
      <div className="dashboard-hero">
        <h1>Stock Council</h1>
        <p>Multi-model investment research powered by LLM deliberation</p>
        <form className="search-form" onSubmit={handleSearch}>
          <input
            className="search-input"
            type="text"
            placeholder="Enter ticker (e.g. AAPL, NVDA, TSLA)"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            autoFocus
          />
          <button className="search-btn" type="submit" disabled={!ticker.trim()}>
            Analyze
          </button>
        </form>
      </div>

      {recentAnalyses.length > 0 && (
        <div className="recent-analyses">
          <h2>Recent Analyses</h2>
          <div className="analyses-grid">
            {recentAnalyses.slice(0, 12).map((a) => (
              <button
                key={a.id}
                className="analysis-card"
                onClick={() => navigate(`/stock/${a.ticker}?analysis=${a.id}`)}
              >
                <div className="card-ticker">{a.ticker}</div>
                <div className="card-meta">
                  {a.verdict && (
                    <span
                      className="card-verdict"
                      style={{ color: VERDICT_COLOR[a.verdict] || '#888' }}
                    >
                      {a.verdict.toUpperCase()}
                      {a.confidence != null ? ` ${a.confidence}%` : ''}
                    </span>
                  )}
                  <span className="card-price">
                    {a.price_at != null ? `$${a.price_at.toFixed(2)}` : ''}
                  </span>
                </div>
                <div className="card-date">
                  {a.created_at ? new Date(a.created_at).toLocaleDateString() : ''}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default Dashboard;
