import { useEffect, useRef } from 'react';
import { createChart, CandlestickSeries } from 'lightweight-charts';
import './PriceChart.css';

function PriceChart({ candles }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !candles?.length) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 300,
      layout: { background: { color: '#fff' }, textColor: '#333' },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      rightPriceScale: { borderColor: '#ddd' },
      timeScale: { borderColor: '#ddd', timeVisible: true },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22a74f',
      downColor: '#e53e3e',
      borderUpColor: '#22a74f',
      borderDownColor: '#e53e3e',
      wickUpColor: '#22a74f',
      wickDownColor: '#e53e3e',
    });

    series.setData(
      candles.map((c) => ({
        time: c.date,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [candles]);

  if (!candles?.length) {
    return <div className="chart-empty">No price data available.</div>;
  }

  return <div ref={containerRef} className="price-chart" />;
}

export default PriceChart;
