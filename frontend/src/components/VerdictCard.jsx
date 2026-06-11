import './VerdictCard.css';

const COLORS = { buy: '#22a74f', hold: '#e6a817', sell: '#e53e3e' };
const LABELS = { buy: 'BUY', hold: 'HOLD', sell: 'SELL' };

function VerdictCard({ verdict, ticker }) {
  if (!verdict) {
    return (
      <div className="verdict-card verdict-null">
        <span>Council verdict not yet parsed — see the full report below.</span>
      </div>
    );
  }

  const color = COLORS[verdict.verdict] || '#888';
  const label = LABELS[verdict.verdict] || verdict.verdict?.toUpperCase();
  const confidence = verdict.confidence ?? 0;
  const targets = verdict.price_targets || {};

  return (
    <div className="verdict-card" style={{ borderLeft: `5px solid ${color}` }}>
      <div className="verdict-top">
        <span className="verdict-badge" style={{ background: color }}>{label}</span>
        <div className="verdict-confidence">
          <span className="confidence-label">Confidence {confidence}%</span>
          <div className="confidence-bar">
            <div
              className="confidence-fill"
              style={{ width: `${confidence}%`, background: color }}
            />
          </div>
        </div>
      </div>

      {verdict.thesis && (
        <p className="verdict-thesis">{verdict.thesis}</p>
      )}

      {Object.keys(targets).length > 0 && (
        <div className="verdict-targets">
          <table className="targets-table">
            <thead>
              <tr>
                <th>Timeframe</th>
                <th>Direction</th>
                <th>Low</th>
                <th>High</th>
              </tr>
            </thead>
            <tbody>
              {['1w', '1m', '3m'].map((tf) => {
                const t = targets[tf];
                if (!t) return null;
                return (
                  <tr key={tf}>
                    <td>{tf === '1w' ? '1 Week' : tf === '1m' ? '1 Month' : '3 Months'}</td>
                    <td>
                      <span className={`dir-badge dir-${t.direction}`}>
                        {t.direction === 'up' ? '▲' : t.direction === 'down' ? '▼' : '→'} {t.direction}
                      </span>
                    </td>
                    <td>{t.low != null ? `$${t.low.toFixed(2)}` : '—'}</td>
                    <td>{t.high != null ? `$${t.high.toFixed(2)}` : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {verdict.key_risks?.length > 0 && (
        <div className="verdict-risks">
          <strong>Key Risks:</strong>
          <ul>
            {verdict.key_risks.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export default VerdictCard;
