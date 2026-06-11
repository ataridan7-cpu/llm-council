import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './StockStage1.css';

const VERDICT_COLOR = { buy: '#22a74f', hold: '#e6a817', sell: '#e53e3e' };
const DIRECTION_ICON = { up: '↑', down: '↓', flat: '→' };

function CouncilSummary({ results }) {
  return (
    <div className="council-summary">
      {results.map((r, i) => {
        const v = r.verdict;
        const color = v ? (VERDICT_COLOR[v.verdict] || '#ccc') : '#e0e0e0';
        return (
          <div key={i} className="cs-badge" style={{ borderColor: color }}>
            <span className="cs-model">{r.model.split('/')[1] || r.model}</span>
            {v ? (
              <>
                <span className="cs-verdict" style={{ background: color }}>
                  {v.verdict.toUpperCase()}
                </span>
                <span className="cs-conf">{v.confidence}%</span>
              </>
            ) : (
              <span className="cs-no-verdict">no verdict</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function InlineVerdict({ verdict }) {
  if (!verdict) return null;
  const color = VERDICT_COLOR[verdict.verdict] || '#ccc';
  const targets = verdict.price_targets || {};
  return (
    <div className="inline-verdict">
      <div className="iv-top">
        <span className="iv-verdict" style={{ background: color }}>
          {verdict.verdict.toUpperCase()}
        </span>
        <span className="iv-conf">Confidence: {verdict.confidence}%</span>
        <div className="iv-conf-bar">
          <div className="iv-conf-fill" style={{ width: `${verdict.confidence}%`, background: color }} />
        </div>
      </div>
      {verdict.thesis && <p className="iv-thesis">{verdict.thesis}</p>}
      {Object.keys(targets).length > 0 && (
        <div className="iv-targets">
          {['1w', '1m', '3m'].map((tf) => {
            const t = targets[tf];
            if (!t) return null;
            return (
              <div key={tf} className="iv-target">
                <span className="iv-tf">{tf}</span>
                <span className="iv-dir" title={t.direction}>
                  {DIRECTION_ICON[t.direction] || ''}
                </span>
                {t.low != null && t.high != null && (
                  <span className="iv-range">${t.low}–${t.high}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {verdict.key_risks?.length > 0 && (
        <div className="iv-risks">
          <strong>Key risks:</strong>
          <ul>
            {verdict.key_risks.slice(0, 3).map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function StockStage1({ results }) {
  const [activeTab, setActiveTab] = useState(0);
  const [showProse, setShowProse] = useState(false);

  if (!results || results.length === 0) return null;
  const active = results[activeTab];

  return (
    <div className="stock-stage1">
      <CouncilSummary results={results} />
      <div className="tabs">
        {results.map((r, i) => {
          const v = r.verdict;
          const color = v ? (VERDICT_COLOR[v.verdict] || '#ccc') : 'transparent';
          return (
            <button
              key={i}
              className={`tab ${activeTab === i ? 'active' : ''}`}
              onClick={() => setActiveTab(i)}
              style={activeTab === i ? { borderBottom: `3px solid ${color}` } : {}}
            >
              {r.model.split('/')[1] || r.model}
              {v && (
                <span className="tab-verdict-dot" style={{ background: color }} />
              )}
            </button>
          );
        })}
      </div>
      <div className="tab-content">
        <InlineVerdict verdict={active.verdict} />
        <button
          className="prose-toggle"
          onClick={() => setShowProse((p) => !p)}
        >
          {showProse ? 'Hide' : 'Show'} full analysis
        </button>
        {showProse && (
          <div className="markdown-content">
            <ReactMarkdown>{active.response}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
