import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import './Dashboard.css';

const TRACKED_TICKERS = ['NVDA', 'INTC', 'AMD', 'AMZN', 'AAPL', 'TSLA', 'NFLX'];

const TICKER_NAMES = {
  NVDA: 'NVIDIA',
  INTC: 'Intel',
  AMD: 'AMD',
  AMZN: 'Amazon',
  AAPL: 'Apple',
  TSLA: 'Tesla',
  NFLX: 'Netflix',
};

const VERDICT_COLOR = { buy: '#22a74f', hold: '#e6a817', sell: '#e53e3e' };

function AlphaBadge({ alpha }) {
  if (alpha == null) return null;
  const pct = (alpha * 100).toFixed(1);
  const positive = alpha >= 0;
  return (
    <span className={`alpha-badge ${positive ? 'pos' : 'neg'}`}>
      {positive ? '+' : ''}{pct}% vs S&P
    </span>
  );
}

function TickerCard({ ticker, analyses }) {
  const navigate = useNavigate();
  const latest = analyses[0];
  const verdict = latest?.verdict;
  const color = verdict ? VERDICT_COLOR[verdict] : '#ccc';

  return (
    <button
      className="ticker-card"
      onClick={() => navigate(`/stock/${ticker}${latest ? `?analysis=${latest.id}` : ''}`)}
      style={{ borderTop: `4px solid ${color}` }}
    >
      <div className="tc-ticker">{ticker}</div>
      <div className="tc-name">{TICKER_NAMES[ticker]}</div>

      {latest ? (
        <>
          <div className="tc-verdict-row">
            {verdict && (
              <span className="tc-verdict" style={{ color }}>
                {verdict.toUpperCase()}
                {latest.confidence != null ? ` · ${latest.confidence}%` : ''}
              </span>
            )}
            {latest.price_at != null && (
              <span className="tc-price">${latest.price_at.toFixed(2)}</span>
            )}
          </div>
          {latest.avg_alpha != null && <AlphaBadge alpha={latest.avg_alpha} />}
          <div className="tc-date">
            {new Date(latest.created_at).toLocaleDateString()}
          </div>
          {analyses.length > 1 && (
            <div className="tc-count">{analyses.length} analyses</div>
          )}
        </>
      ) : (
        <div className="tc-none">No analysis yet</div>
      )}
    </button>
  );
}

function Dashboard() {
  const [analysesByTicker, setAnalysesByTicker] = useState({});
  const [predictionsByTicker, setPredictionsByTicker] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadAll();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    try {
      // Fetch analyses and predictions for all tickers in parallel
      const results = await Promise.allSettled(
        TRACKED_TICKERS.map((t) => api.listAnalyses(t).then((a) => ({ ticker: t, data: a })))
      );
      const predsResults = await Promise.allSettled(
        TRACKED_TICKERS.map((t) => api.listPredictions(t).then((p) => ({ ticker: t, data: p })))
      );

      const byTicker = {};
      results.forEach((r) => {
        if (r.status === 'fulfilled') byTicker[r.value.ticker] = r.value.data;
      });
      setAnalysesByTicker(byTicker);

      const predsByTicker = {};
      predsResults.forEach((r) => {
        if (r.status === 'fulfilled') predsByTicker[r.value.ticker] = r.value.data;
      });
      setPredictionsByTicker(predsByTicker);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Enrich analyses with avg alpha from predictions
  const enrichedAnalyses = (ticker) => {
    const analyses = analysesByTicker[ticker] || [];
    const preds = predictionsByTicker[ticker] || [];

    // Build a map: analysis_id -> avg evaluated alpha
    const alphaByAnalysis = {};
    for (const pred of preds) {
      if (!pred.analysis_id) continue;
      const outcomes = pred.outcomes_summary || {};
      // Get alpha from predictions (not in list summary — skip for now, show in detail)
    }

    return analyses;
  };

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <h1>Stock Council</h1>
          <p>LLM investment committee tracking 7 tech stocks vs S&amp;P 500</p>
        </div>
        <button className="refresh-btn" onClick={loadAll} disabled={loading}>
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      <div className="ticker-grid">
        {TRACKED_TICKERS.map((ticker) => (
          <TickerCard
            key={ticker}
            ticker={ticker}
            analyses={analysesByTicker[ticker] || []}
          />
        ))}
      </div>

      <div className="dashboard-hint">
        Click any card to view the full analysis, price chart, and research dossier.
        Run a new council analysis from the stock page.
      </div>
    </div>
  );
}

export default Dashboard;
