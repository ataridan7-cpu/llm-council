import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import './Dashboard.css';

const TRACKED_TICKERS = ['NVDA', 'INTC', 'AMD', 'AMZN', 'AAPL', 'TSLA', 'NFLX'];

const TICKER_NAMES = {
  NVDA: 'NVIDIA', INTC: 'Intel', AMD: 'AMD',
  AMZN: 'Amazon', AAPL: 'Apple', TSLA: 'Tesla', NFLX: 'Netflix',
};

const VERDICT_COLOR = { buy: '#22a74f', hold: '#e6a817', sell: '#e53e3e' };
const SIGNAL_COLOR = { bullish: '#22a74f', neutral: '#e6a817', bearish: '#e53e3e' };
const ALERT_ICON = { big_move: '⚡', stale_analysis: '⚠️', no_analysis: '📭', prediction_due: '🔔', in_target: '🎯' };

function TickerCard({ row }) {
  const navigate = useNavigate();
  const ticker = row.ticker;
  const verdict = row.latest_verdict;
  const color = verdict ? (VERDICT_COLOR[verdict] || '#ccc') : '#e0e0e0';
  const dayPct = row.day_change_pct;
  const dayPos = dayPct != null && dayPct >= 0;

  return (
    <button
      className="ticker-card"
      onClick={() => navigate(`/stock/${ticker}`)}
      style={{ borderTop: `4px solid ${color}` }}
    >
      <div className="tc-head">
        <span className="tc-ticker">{ticker}</span>
        {row.alerts?.length > 0 && (
          <span className="tc-alert-dot" title={row.alerts[0].message}>
            {ALERT_ICON[row.alerts[0].type] || '!'}
          </span>
        )}
      </div>
      <div className="tc-name">{TICKER_NAMES[ticker] || row.name}</div>

      {row.price != null ? (
        <>
          <div className="tc-price-row">
            <span className="tc-price">${row.price.toFixed(2)}</span>
            {dayPct != null && (
              <span className={`tc-day ${dayPos ? 'pos' : 'neg'}`}>
                {dayPos ? '+' : ''}{dayPct.toFixed(2)}%
              </span>
            )}
          </div>
          {verdict && (
            <div className="tc-verdict" style={{ color }}>
              {verdict.toUpperCase()}
              {row.latest_confidence != null ? ` · ${row.latest_confidence}%` : ''}
              {row.verdict_age_days != null && (
                <span className="tc-age"> · {row.verdict_age_days}d ago</span>
              )}
            </div>
          )}
          {!verdict && <div className="tc-none">No analysis yet</div>}
        </>
      ) : (
        <div className="tc-none">Loading...</div>
      )}
      {row.quick_signal && (
        <div className="tc-signal" style={{ color: SIGNAL_COLOR[row.quick_signal.signal] || '#888' }}>
          {row.quick_signal.signal} signal
        </div>
      )}
    </button>
  );
}

function BootstrapBar({ bootstrapStatus, bootstrapLog, onClose }) {
  if (!bootstrapStatus) return null;
  return (
    <div className="bootstrap-bar">
      <div className="bb-header">
        <strong>Running Council Analyses</strong>
        {bootstrapStatus === 'done' && (
          <button className="bb-close" onClick={onClose}>✕</button>
        )}
      </div>
      <div className="bb-log">
        {bootstrapLog.map((entry, i) => (
          <div key={i} className={`bb-entry ${entry.type}`}>{entry.message}</div>
        ))}
        {bootstrapStatus === 'running' && <div className="bb-spinner">Running next ticker...</div>}
      </div>
    </div>
  );
}

function PortfolioBar({ portfolio }) {
  if (!portfolio || portfolio.portfolio?.n_evaluated === 0) return null;
  const p = portfolio.portfolio;
  const alphaPos = p.avg_alpha != null && p.avg_alpha >= 0;
  return (
    <div className="portfolio-bar">
      <span className="pb-label">Portfolio vs S&amp;P 500</span>
      {p.avg_alpha != null && (
        <span className="pb-kpi" style={{ color: alphaPos ? '#22a74f' : '#e53e3e' }}>
          Avg alpha: {alphaPos ? '+' : ''}{(p.avg_alpha * 100).toFixed(2)}%
        </span>
      )}
      {p.beat_spy_rate != null && (
        <span className="pb-kpi">
          Beat SPY: {Math.round(p.beat_spy_rate * 100)}%
        </span>
      )}
      {p.verdict_hit_rate != null && (
        <span className="pb-kpi">
          Verdict hit: {Math.round(p.verdict_hit_rate * 100)}%
        </span>
      )}
      <span className="pb-n">({p.n_evaluated} evaluated)</span>
    </div>
  );
}

function Dashboard() {
  const [rows, setRows] = useState(TRACKED_TICKERS.map((t) => ({ ticker: t, price: null })));
  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [bootstrapStatus, setBootstrapStatus] = useState(null); // null | 'running' | 'done'
  const [bootstrapLog, setBootstrapLog] = useState([]);

  useEffect(() => {
    loadWatchlist();
    api.getPortfolio().then(setPortfolio).catch(console.error);
  }, []);

  const loadWatchlist = async () => {
    setLoading(true);
    try {
      const data = await api.getWatchlist();
      setRows(data.tickers);
    } catch (e) {
      console.error('Watchlist load failed:', e);
    } finally {
      setLoading(false);
    }
  };

  const handleBootstrap = async () => {
    setBootstrapStatus('running');
    setBootstrapLog([{ type: 'info', message: 'Starting analyses for all missing tickers...' }]);

    try {
      await api.bootstrapAnalyses((type, event) => {
        switch (type) {
          case 'bootstrap_start':
            setBootstrapLog((prev) => [
              ...prev,
              { type: 'info', message: `${event.data.total} ticker(s) need analysis.` },
            ]);
            break;
          case 'bootstrap_ticker_start':
            setBootstrapLog((prev) => [
              ...prev,
              { type: 'info', message: `⏳ ${event.data.ticker}: running council analysis...` },
            ]);
            break;
          case 'bootstrap_ticker_complete':
            setBootstrapLog((prev) => [
              ...prev,
              { type: 'success', message: `✓ ${event.data.ticker}: analysis complete` },
            ]);
            break;
          case 'bootstrap_error':
            setBootstrapLog((prev) => [
              ...prev,
              { type: 'error', message: `✗ ${event.data.ticker}: ${event.data.message}` },
            ]);
            break;
          case 'bootstrap_complete':
            setBootstrapLog((prev) => [
              ...prev,
              {
                type: 'success',
                message: `Done. ${event.data.completed}/${event.data.total} analyses completed.`,
              },
            ]);
            setBootstrapStatus('done');
            loadWatchlist();
            break;
          default:
            break;
        }
      });
    } catch (e) {
      setBootstrapLog((prev) => [...prev, { type: 'error', message: `Error: ${e.message}` }]);
      setBootstrapStatus('done');
    }
  };

  const missingAnalyses = rows.filter((r) => !r.latest_verdict).length;

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <h1>Stock Council</h1>
          <p>LLM investment committee · 7 tech stocks vs S&amp;P 500</p>
        </div>
        <div className="header-actions">
          {missingAnalyses > 0 && !bootstrapStatus && (
            <button className="bootstrap-btn" onClick={handleBootstrap}>
              Run All Analyses ({missingAnalyses} missing)
            </button>
          )}
          <button className="refresh-btn" onClick={loadWatchlist} disabled={loading}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      </div>

      <PortfolioBar portfolio={portfolio} />

      <BootstrapBar
        bootstrapStatus={bootstrapStatus}
        bootstrapLog={bootstrapLog}
        onClose={() => { setBootstrapStatus(null); setBootstrapLog([]); }}
      />

      <div className="ticker-grid">
        {rows.map((row) => (
          <TickerCard key={row.ticker} row={row} />
        ))}
      </div>

      {/* Alerts summary */}
      {rows.some((r) => r.alerts?.length > 0) && (
        <div className="alerts-panel">
          <h3>Alerts</h3>
          {rows.flatMap((r) =>
            (r.alerts || []).map((a, i) => (
              <div key={`${r.ticker}-${i}`} className="alert-item">
                <span className="alert-icon">{ALERT_ICON[a.type] || '!'}</span>
                <strong>{r.ticker}</strong>: {a.message}
              </div>
            ))
          )}
        </div>
      )}

      <div className="dashboard-hint">
        Click any card to view full analysis and research dossier. Prices refresh on page load.
        Head to <strong>Scorecard</strong> to evaluate predictions against S&amp;P 500.
      </div>
    </div>
  );
}

export default Dashboard;
