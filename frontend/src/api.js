/**
 * API client for the LLM Council backend.
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001';

export const api = {
  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`);
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Generic SSE stream reader.
   */
  async streamRequest(path, body, onEvent) {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete last line
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6));
            onEvent(event.type, event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }
  },

  /**
   * Send a message and receive streaming updates.
   */
  async sendMessageStream(conversationId, content, onEvent) {
    return this.streamRequest(
      `/api/conversations/${conversationId}/message/stream`,
      { content },
      onEvent
    );
  },

  // Stock analysis

  async runAnalysisStream(ticker, onEvent) {
    return this.streamRequest('/api/analyses/stream', { ticker }, onEvent);
  },

  async runAnalysis(ticker) {
    const response = await fetch(`${API_BASE}/api/analyses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker }),
    });
    if (!response.ok) throw new Error(`Failed to run analysis: ${response.status}`);
    return response.json();
  },

  async listAnalyses(ticker) {
    const url = ticker
      ? `${API_BASE}/api/analyses?ticker=${encodeURIComponent(ticker)}`
      : `${API_BASE}/api/analyses`;
    const response = await fetch(url);
    if (!response.ok) throw new Error('Failed to list analyses');
    return response.json();
  },

  async getAnalysis(id) {
    const response = await fetch(`${API_BASE}/api/analyses/${id}`);
    if (!response.ok) throw new Error('Analysis not found');
    return response.json();
  },

  async getStockOverview(ticker) {
    const response = await fetch(`${API_BASE}/api/stocks/${encodeURIComponent(ticker)}/overview`);
    if (!response.ok) throw new Error(`Unknown ticker: ${ticker}`);
    return response.json();
  },

  async getStockHistory(ticker, period = '1y', interval = '1d') {
    const response = await fetch(
      `${API_BASE}/api/stocks/${encodeURIComponent(ticker)}/history?period=${period}&interval=${interval}`
    );
    if (!response.ok) throw new Error('Failed to get price history');
    return response.json();
  },

  // Scorecard

  async getScorecard() {
    const response = await fetch(`${API_BASE}/api/scorecard`);
    if (!response.ok) throw new Error('Failed to get scorecard');
    return response.json();
  },

  async triggerEvaluate() {
    const response = await fetch(`${API_BASE}/api/scorecard/evaluate`, { method: 'POST' });
    if (!response.ok) throw new Error('Failed to trigger evaluation');
    return response.json();
  },

  async listPredictions(ticker, status, full = false) {
    const params = new URLSearchParams();
    if (ticker) params.append('ticker', ticker);
    if (status) params.append('status', status);
    if (full) params.append('full', 'true');
    const response = await fetch(`${API_BASE}/api/predictions?${params}`);
    if (!response.ok) throw new Error('Failed to list predictions');
    return response.json();
  },

  // Watchlist (live quotes + alerts, no LLM)
  async getWatchlist() {
    const response = await fetch(`${API_BASE}/api/watchlist`);
    if (!response.ok) throw new Error('Failed to get watchlist');
    return response.json();
  },

  // Bootstrap all 7 tickers (SSE)
  async bootstrapAnalyses(onEvent) {
    return this.streamRequest('/api/analyses/bootstrap', {}, onEvent);
  },
};
