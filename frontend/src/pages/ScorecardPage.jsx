import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import './ScorecardPage.css';

function HitBar({ rate }) {
  if (rate == null) return <span className="no-data">—</span>;
  const pct = Math.round(rate * 100);
  const color = pct >= 60 ? '#22a74f' : pct >= 45 ? '#e6a817' : '#e53e3e';
  return (
    <div className="hit-bar-wrap">
      <div className="hit-bar">
        <div className="hit-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="hit-pct">{pct}%</span>
    </div>
  );
}

function AlphaCell({ alpha, beatRate }) {
  if (alpha == null) return <span className="no-data">—</span>;
  const pct = (alpha * 100).toFixed(1);
  const pos = alpha >= 0;
  const beatPct = beatRate != null ? Math.round(beatRate * 100) : null;
  return (
    <div>
      <span style={{ fontWeight: 700, color: pos ? '#22a74f' : '#e53e3e' }}>
        {pos ? '+' : ''}{pct}%
      </span>
      {beatPct != null && (
        <span className="beat-sub"> ({beatPct}% beat SPY)</span>
      )}
    </div>
  );
}

const VERDICT_COLOR = { buy: '#22a74f', hold: '#e6a817', sell: '#e53e3e' };

function PortfolioPanel({ portfolio }) {
  const navigate = useNavigate();
  if (!portfolio) return null;
  const p = portfolio.portfolio;
  const tickers = portfolio.tickers || [];

  if (p.n_evaluated === 0) return null;

  const alphaPos = p.avg_alpha != null && p.avg_alpha >= 0;

  return (
    <div className="portfolio-panel">
      <h2>Portfolio Summary</h2>
      <p className="portfolio-sub">
        Equal-weight council verdicts across all 7 tickers vs S&amp;P 500 (SPY benchmark)
      </p>
      <div className="portfolio-kpis">
        <div className="kpi">
          <span className="kpi-label">Avg Alpha vs SPY</span>
          <span className="kpi-value" style={{ color: alphaPos ? '#22a74f' : '#e53e3e' }}>
            {p.avg_alpha != null ? `${alphaPos ? '+' : ''}${(p.avg_alpha * 100).toFixed(2)}%` : '—'}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Beat SPY Rate</span>
          <span className="kpi-value">
            {p.beat_spy_rate != null ? `${Math.round(p.beat_spy_rate * 100)}%` : '—'}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Verdict Hit Rate</span>
          <span className="kpi-value">
            {p.verdict_hit_rate != null ? `${Math.round(p.verdict_hit_rate * 100)}%` : '—'}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Avg Return</span>
          <span className="kpi-value" style={{ color: p.avg_return >= 0 ? '#22a74f' : '#e53e3e' }}>
            {p.avg_return != null ? `${p.avg_return >= 0 ? '+' : ''}${(p.avg_return * 100).toFixed(2)}%` : '—'}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Positions Evaluated</span>
          <span className="kpi-value">{p.n_evaluated}</span>
        </div>
      </div>

      <div className="portfolio-ticker-grid">
        {tickers.map((row) => {
          const tf1w = row.timeframes?.['1w'];
          const alpha1w = tf1w?.avg_alpha;
          const pos = alpha1w != null && alpha1w >= 0;
          const latestVerdict = Object.entries(row.verdicts || {})
            .sort((a, b) => b[1] - a[1])[0]?.[0];
          return (
            <button
              key={row.ticker}
              className="portfolio-ticker-card"
              onClick={() => navigate(`/stock/${row.ticker}`)}
            >
              <div className="ptc-ticker">{row.ticker}</div>
              {latestVerdict && (
                <div className="ptc-verdict" style={{ color: VERDICT_COLOR[latestVerdict] }}>
                  {latestVerdict.toUpperCase()}
                </div>
              )}
              {alpha1w != null ? (
                <div className="ptc-alpha" style={{ color: pos ? '#22a74f' : '#e53e3e' }}>
                  {pos ? '+' : ''}{(alpha1w * 100).toFixed(1)}% α (1w)
                </div>
              ) : (
                <div className="ptc-alpha no-data">No data yet</div>
              )}
              <div className="ptc-meta">{row.n_evaluated} evaluated · {row.n_pending} pending</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ScorecardPage() {
  const [data, setData] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState(null);

  const load = () => {
    api.getScorecard().then(setData).catch(console.error);
    api.getPortfolio().then(setPortfolio).catch(console.error);
  };

  useEffect(() => { load(); }, []);

  const handleEvaluate = async () => {
    setEvaluating(true);
    try {
      const result = await api.triggerEvaluate();
      setEvalResult(result);
      await load();
    } catch (e) {
      console.error(e);
    } finally {
      setEvaluating(false);
    }
  };

  const leaderboard = data?.leaderboard || [];
  // Put council first
  const sorted = [...leaderboard].sort((a, b) => {
    if (a.entity === 'council') return -1;
    if (b.entity === 'council') return 1;
    return -(a.overall?.verdict_hit_rate || 0) + (b.overall?.verdict_hit_rate || 0);
  });

  return (
    <div className="scorecard-page">
      <div className="scorecard-header">
        <div>
          <h1>Prediction Scorecard</h1>
          <p className="scorecard-sub">
            Tracking NVDA · INTC · AMD · AMZN · AAPL · TSLA · NFLX vs S&P 500 (SPY)
          </p>
        </div>
        <div className="scorecard-actions">
          {evalResult && (
            <span className="eval-result">
              Evaluated {evalResult.evaluated} · Skipped {evalResult.skipped}
            </span>
          )}
          <button className="eval-btn" onClick={handleEvaluate} disabled={evaluating}>
            {evaluating ? 'Evaluating...' : 'Evaluate Now'}
          </button>
        </div>
      </div>

      <PortfolioPanel portfolio={portfolio} />

      {leaderboard.length === 0 ? (
        <div className="scorecard-empty">
          No evaluated predictions yet. Run analyses on the stocks and return after the 1-week, 1-month, and 3-month target dates pass — then click <strong>Evaluate Now</strong>.
        </div>
      ) : (
        <>
          <div className="scorecard-legend">
            <strong>Verdict hit</strong> = buy paid off (&gt;+2%), sell paid off (&lt;-2%), hold was flat (±2%).&nbsp;
            <strong>Alpha</strong> = stock return − S&P 500 return over same window (council picks only).
          </div>
          <div className="table-wrap">
            <table className="leaderboard-table">
              <thead>
                <tr>
                  <th rowSpan={2}>Model / Entity</th>
                  <th rowSpan={2} className="center">N</th>
                  <th colSpan={2} className="center tf-header">1 Week</th>
                  <th colSpan={2} className="center tf-header">1 Month</th>
                  <th colSpan={2} className="center tf-header">3 Month</th>
                  <th colSpan={3} className="center tf-header overall-header">Overall</th>
                </tr>
                <tr className="sub-header">
                  <th>Dir %</th><th>Verdict %</th>
                  <th>Dir %</th><th>Verdict %</th>
                  <th>Dir %</th><th>Verdict %</th>
                  <th>Dir %</th><th>Verdict %</th><th>Alpha vs SPY</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row) => {
                  const tf = (timeframe) => row.timeframes?.[timeframe] || {};
                  const overall = row.overall || {};
                  const isCouncil = row.entity === 'council';
                  return (
                    <tr key={row.entity} className={isCouncil ? 'council-row' : ''}>
                      <td className="entity-cell">
                        {isCouncil
                          ? <><strong>Council</strong> <span className="council-sub">(Chairman)</span></>
                          : (row.entity.split('/')[1] || row.entity)}
                      </td>
                      <td className="center n-cell">{overall.n || 0}</td>
                      <td><HitBar rate={tf('1w').direction_hit_rate} /></td>
                      <td><HitBar rate={tf('1w').verdict_hit_rate} /></td>
                      <td><HitBar rate={tf('1m').direction_hit_rate} /></td>
                      <td><HitBar rate={tf('1m').verdict_hit_rate} /></td>
                      <td><HitBar rate={tf('3m').direction_hit_rate} /></td>
                      <td><HitBar rate={tf('3m').verdict_hit_rate} /></td>
                      <td><HitBar rate={overall.direction_hit_rate} /></td>
                      <td><HitBar rate={overall.verdict_hit_rate} /></td>
                      <td>
                        {isCouncil
                          ? <AlphaCell alpha={overall.avg_alpha} beatRate={overall.beat_spy_rate} />
                          : <span className="no-data">—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default ScorecardPage;
