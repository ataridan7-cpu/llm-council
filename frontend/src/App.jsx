import { Routes, Route } from 'react-router-dom';
import NavBar from './components/NavBar';
import Disclaimer from './components/Disclaimer';
import Dashboard from './pages/Dashboard';
import StockPage from './pages/StockPage';
import ChatPage from './pages/ChatPage';
import ScorecardPage from './pages/ScorecardPage';
import NotFound from './pages/NotFound';
import './App.css';

function App() {
  return (
    <div className="app-shell">
      <NavBar />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/stock/:ticker" element={<StockPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/scorecard" element={<ScorecardPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <Disclaimer />
    </div>
  );
}

export default App;
