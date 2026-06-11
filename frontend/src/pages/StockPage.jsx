import { useState, useEffect, useCallback } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import PriceChart from '../components/PriceChart';
import VerdictCard from '../components/VerdictCard';
import DossierView from '../components/DossierView';
import Stage1 from '../components/Stage1';
import Stage2 from '../components/Stage2';
import Stage3 from '../components/Stage3';
import './StockPage.css';

const VERDICT_COLOR = { buy: '#22a74f', hold: '#e6a817', sell: '#e53e3e' };

function StatusBar({ status }) {
  if (!status) return null;
  return <div className="status-bar">{status}</div>;
}

function StockPage() {
  const { ticker } = useParams();
  const [searchParams] = useSearchParams();
  const initialAnalysisId = searchParams.get('analysis');

  const [overview, setOverview] = useState(null);
  const [history, setHistory] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus] = useState('');
  const [streamState, setStreamState] = useState(null); // live streaming state
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!ticker) return;
    setError(null);
    setAnalysis(null);
    setStreamState(null);

    Promise.all([
      api.getStockOverview(ticker).then(setOverview).catch(() => setError(`Unknown ticker: ${ticker}`)),
      api.getStockHistory(ticker).then(setHistory).catch(console.error),
      api.listAnalyses(ticker).then(setAnalyses).catch(console.error),
    ]);
  }, [ticker]);

  // Load a specific analysis by id if ?analysis= param
  useEffect(() => {
    if (initialAnalysisId) {
      api.getAnalysis(initialAnalysisId).then(setAnalysis).catch(console.error);
    }
  }, [initialAnalysisId]);

  const runAnalysis = useCallback(async () => {
    if (isRunning) return;
    setIsRunning(true);
    setError(null);
    setStreamState({
      stage0Sections: [],
      stage1: null,
      stage2: null,
      stage3: null,
      metadata: null,
      loading: { stage0: false, stage1: false, stage2: false, stage3: false },
    });

    try {
      await api.runAnalysisStream(ticker, (type, event) => {
        switch (type) {
          case 'analysis_start':
            setStatus(`Fetching market data for ${ticker}...`);
            break;
          case 'data_fetch_complete':
            setStatus('Market data fetched. Starting research agents...');
            break;
          case 'stage0_start':
            setStatus('Stage 0: Research agents analyzing...');
            setStreamState((prev) => ({ ...prev, loading: { ...prev.loading, stage0: true } }));
            break;
          case 'stage0_agent_complete':
            setStatus(`Research: ${event.data.title} complete`);
            setStreamState((prev) => ({
              ...prev,
              stage0Sections: [...prev.stage0Sections, event.data],
            }));
            break;
          case 'stage0_complete':
            setStatus('Research dossier complete. Running council...');
            setStreamState((prev) => ({ ...prev, loading: { ...prev.loading, stage0: false } }));
            break;
          case 'stage1_start':
            setStatus('Stage 1: Council members analyzing...');
            setStreamState((prev) => ({ ...prev, loading: { ...prev.loading, stage1: true } }));
            break;
          case 'stage1_complete':
            setStreamState((prev) => ({
              ...prev,
              stage1: event.data,
              loading: { ...prev.loading, stage1: false },
            }));
            setStatus('Stage 2: Peer review...');
            break;
          case 'stage2_start':
            setStreamState((prev) => ({ ...prev, loading: { ...prev.loading, stage2: true } }));
            break;
          case 'stage2_complete':
            setStreamState((prev) => ({
              ...prev,
              stage2: event.data,
              metadata: event.metadata,
              loading: { ...prev.loading, stage2: false },
            }));
            setStatus('Stage 3: Chairman synthesizing...');
            break;
          case 'stage3_start':
            setStreamState((prev) => ({ ...prev, loading: { ...prev.loading, stage3: true } }));
            break;
          case 'stage3_complete':
            setStreamState((prev) => ({
              ...prev,
              stage3: event.data,
              loading: { ...prev.loading, stage3: false },
            }));
            break;
          case 'prediction_recorded':
            setStatus('Prediction recorded.');
            break;
          case 'complete': {
            const analysisId = event.data?.analysis_id;
            if (analysisId) {
              api.getAnalysis(analysisId).then((a) => {
                setAnalysis(a);
                setStreamState(null);
                setAnalyses((prev) => [
                  {
                    id: a.id,
                    ticker: a.ticker,
                    created_at: a.created_at,
                    verdict: a.stage3?.verdict?.verdict,
                    confidence: a.stage3?.verdict?.confidence,
                    price_at: a.market_snapshot?.price,
                  },
                  ...prev,
                ]);
              });
            }
            setStatus('');
            setIsRunning(false);
            break;
          }
          case 'error':
            setError(event.message);
            setStatus('');
            setIsRunning(false);
            setStreamState(null);
            break;
          default:
            break;
        }
      });
    } catch (e) {
      setError(e.message);
      setStatus('');
      setIsRunning(false);
      setStreamState(null);
    }
  }, [ticker, isRunning]);

  const selectAnalysis = async (id) => {
    const a = await api.getAnalysis(id).catch(console.error);
    if (a) setAnalysis(a);
  };

  const quote = overview?.quote;
  const displayAnalysis = analysis || (streamState ? {
    dossier: { sections: streamState.stage0Sections },
    stage1: streamState.stage1,
    stage2: streamState.stage2,
    stage3: streamState.stage3,
    metadata: streamState.metadata,
  } : null);

  if (error) {
    return (
      <div className="stock-page">
        <div className="stock-error">{error}</div>
      </div>
    );
  }

  return (
    <div className="stock-page">
      <div className="stock-header">
        <div className="stock-title">
          <h1>{ticker}</h1>
          {quote && (
            <div className="stock-quote">
              <span className="quote-price">${quote.price?.toFixed(2)}</span>
              <span className="quote-name">{quote.name}</span>
              {quote.prev_close && (
                <span className={`quote-change ${quote.price >= quote.prev_close ? 'pos' : 'neg'}`}>
                  {((quote.price / quote.prev_close - 1) * 100).toFixed(2)}%
                </span>
              )}
            </div>
          )}
        </div>
        <button
          className="run-btn"
          onClick={runAnalysis}
          disabled={isRunning}
        >
          {isRunning ? 'Running Council...' : 'Run Council Analysis'}
        </button>
      </div>

      <StatusBar status={status} />

      <PriceChart candles={history?.candles || []} />

      {analyses.length > 1 && (
        <div className="analysis-history">
          <strong>Past analyses:</strong>
          {analyses.slice(0, 8).map((a) => (
            <button
              key={a.id}
              className={`analysis-pill${analysis?.id === a.id ? ' active' : ''}`}
              onClick={() => selectAnalysis(a.id)}
            >
              {new Date(a.created_at).toLocaleDateString()}
              {a.verdict && (
                <span style={{ color: VERDICT_COLOR[a.verdict], marginLeft: 4 }}>
                  {a.verdict.toUpperCase()}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {displayAnalysis && (
        <>
          {displayAnalysis.stage3?.verdict && (
            <section className="stock-section">
              <h2>Council Verdict</h2>
              <VerdictCard verdict={displayAnalysis.stage3.verdict} ticker={ticker} />
            </section>
          )}

          {displayAnalysis.dossier?.sections?.length > 0 && (
            <section className="stock-section">
              <h2>Research Dossier</h2>
              <DossierView dossier={displayAnalysis.dossier} />
            </section>
          )}

          {displayAnalysis.stage1 && (
            <section className="stock-section">
              <h2>Stage 1 — Council Verdicts</h2>
              <Stage1 results={displayAnalysis.stage1} />
            </section>
          )}

          {displayAnalysis.stage2 && displayAnalysis.metadata && (
            <section className="stock-section">
              <h2>Stage 2 — Peer Rankings</h2>
              <Stage2
                results={displayAnalysis.stage2}
                labelToModel={displayAnalysis.metadata.label_to_model}
                aggregateRankings={displayAnalysis.metadata.aggregate_rankings}
              />
            </section>
          )}

          {displayAnalysis.stage3 && (
            <section className="stock-section">
              <h2>Stage 3 — Chairman Report</h2>
              <Stage3 result={displayAnalysis.stage3} />
            </section>
          )}
        </>
      )}

      {!displayAnalysis && !isRunning && (
        <div className="stock-empty">
          No analysis yet. Click <strong>Run Council Analysis</strong> to start.
        </div>
      )}
    </div>
  );
}

export default StockPage;
