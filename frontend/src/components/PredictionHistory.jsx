import './PredictionHistory.css';

const STATUS_ICON = {
  pending: '⏳',
  evaluated: null,
  unavailable: '—',
};

const VERDICT_COLOR = { buy: '#22a74f', hold: '#e6a817', sell: '#e53e3e' };

function OutcomeCell({ outcome }) {
  if (!outcome) return <td className="ph-cell muted">—</td>;

  const { status, actual_return, spy_return, alpha, verdict_hit } = outcome;

  if (status === 'pending') return <td className="ph-cell muted">⏳ pending</td>;
  if (status === 'unavailable') return <td className="ph-cell muted">n/a</td>;

  const ret = actual_return != null ? `${(actual_return * 100).toFixed(1)}%` : '—';
  const hit = verdict_hit != null ? (verdict_hit ? '✓' : '✗') : '';
  const hitColor = verdict_hit ? '#22a74f' : '#e53e3e';
  const alphaVal = alpha != null ? `${alpha >= 0 ? '+' : ''}${(alpha * 100).toFixed(1)}% α` : '';
  const alphaColor = alpha != null ? (alpha >= 0 ? '#22a74f' : '#e53e3e') : '#aaa';

  return (
    <td className="ph-cell">
      <span style={{ color: hitColor, fontWeight: 700, marginRight: 4 }}>{hit}</span>
      <span>{ret}</span>
      {alphaVal && (
        <span style={{ color: alphaColor, fontSize: 10, marginLeft: 5 }}>{alphaVal}</span>
      )}
    </td>
  );
}

function PredictionHistory({ predictions }) {
  if (!predictions || predictions.length === 0) {
    return (
      <div className="ph-empty">
        No predictions recorded yet. Run an analysis to start tracking.
      </div>
    );
  }

  return (
    <div className="ph-wrap">
      <table className="ph-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Price</th>
            <th>Verdict</th>
            <th>1 Week</th>
            <th>1 Month</th>
            <th>3 Month</th>
          </tr>
        </thead>
        <tbody>
          {predictions.map((pred) => {
            const cv = pred.council_verdict;
            const verdict = typeof cv === 'object' ? cv?.verdict : cv;
            const outcomes = pred.outcomes || {};
            return (
              <tr key={pred.id}>
                <td className="ph-cell">
                  {pred.created_at ? new Date(pred.created_at).toLocaleDateString() : '—'}
                </td>
                <td className="ph-cell">
                  {pred.price_at_prediction != null
                    ? `$${pred.price_at_prediction.toFixed(2)}`
                    : '—'}
                </td>
                <td className="ph-cell">
                  {verdict ? (
                    <span style={{ color: VERDICT_COLOR[verdict] || '#888', fontWeight: 700 }}>
                      {verdict.toUpperCase()}
                    </span>
                  ) : '—'}
                </td>
                <OutcomeCell outcome={outcomes['1w']} />
                <OutcomeCell outcome={outcomes['1m']} />
                <OutcomeCell outcome={outcomes['3m']} />
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="ph-legend">
        ✓ = verdict was right · ✗ = wrong · α = alpha vs S&P 500 over same window
      </div>
    </div>
  );
}

export default PredictionHistory;
