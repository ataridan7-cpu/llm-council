import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './DossierView.css';

function DossierView({ dossier }) {
  const sections = dossier?.sections || [];
  const [activeTab, setActiveTab] = useState(0);

  if (!sections.length) {
    return <div className="dossier-empty">No research dossier available.</div>;
  }

  const active = sections[activeTab];

  return (
    <div className="dossier-view">
      <div className="dossier-tabs">
        {sections.map((s, i) => (
          <button
            key={s.role}
            className={`dossier-tab${i === activeTab ? ' active' : ''}`}
            onClick={() => setActiveTab(i)}
          >
            {s.title}
            <span className="dossier-model">{s.model?.split('/')[1] || s.model}</span>
          </button>
        ))}
      </div>
      <div className="dossier-body markdown-content">
        <ReactMarkdown>{active.report}</ReactMarkdown>
      </div>
    </div>
  );
}

export default DossierView;
