import { useState, useEffect } from 'react';
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

function ScorecardPage() {
  const [data, setData] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState(null);

  const load = () => api.getScorecard().then(setData).catch(console.error);

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

  return (
    <div className="scorecard-page">
      <div className="scorecard-header">
        <h1>Prediction Scorecard</h1>
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

      {leaderboard.length === 0 ? (
        <div className="scorecard-empty">
          No evaluated predictions yet. Run some analyses and come back after their target dates.
        </div>
      ) : (
        <table className="leaderboard-table">
          <thead>
            <tr>
              <th>Model / Entity</th>
              <th>Predictions</th>
              <th colSpan={2}>1 Week</th>
              <th colSpan={2}>1 Month</th>
              <th colSpan={2}>3 Month</th>
              <th colSpan={2}>Overall</th>
            </tr>
            <tr className="sub-header">
              <th></th>
              <th></th>
              <th>Direction</th><th>Verdict</th>
              <th>Direction</th><th>Verdict</th>
              <th>Direction</th><th>Verdict</th>
              <th>Direction</th><th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {leaderboard.map((row) => {
              const tf = (timeframe) => row.timeframes?.[timeframe] || {};
              const overall = row.overall || {};
              return (
                <tr key={row.entity}>
                  <td className="entity-cell">
                    {row.entity === 'council'
                      ? <strong>Council (Chairman)</strong>
                      : row.entity.split('/')[1] || row.entity}
                  </td>
                  <td className="n-cell">{overall.n || 0}</td>
                  <td><HitBar rate={tf('1w').direction_hit_rate} /></td>
                  <td><HitBar rate={tf('1w').verdict_hit_rate} /></td>
                  <td><HitBar rate={tf('1m').direction_hit_rate} /></td>
                  <td><HitBar rate={tf('1m').verdict_hit_rate} /></td>
                  <td><HitBar rate={tf('3m').direction_hit_rate} /></td>
                  <td><HitBar rate={tf('3m').verdict_hit_rate} /></td>
                  <td><HitBar rate={overall.direction_hit_rate} /></td>
                  <td><HitBar rate={overall.verdict_hit_rate} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default ScorecardPage;
