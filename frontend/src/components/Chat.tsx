import { useState } from 'react';
import { apiPost, apiStream } from '../api/client';
import { getCardImage, getCardName } from '../utils/cardMap';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface Props {
  initData: string;
  sessionId: string;
  layoutType: string;
  cards: number[];
  onNewReading: () => void;
}

export default function Chat({ initData, sessionId, layoutType, cards, onNewReading }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!question.trim() || loading) return;

    const userMsg = question.trim();
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }]);
    setQuestion('');
    setLoading(true);

    let assistantContent = '';
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

    try {
      await apiStream(
        '/api/v1/tarot/predict/stream',
        {
          session_id: sessionId,
          layout_type: layoutType,
          cards,
          question: userMsg,
        },
        initData,
        (chunk) => {
          assistantContent += chunk;
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: 'assistant', content: assistantContent };
            return updated;
          });
        },
        () => setLoading(false),
      );
    } catch {
      setMessages((prev) => prev.slice(0, -1));
      setLoading(false);
    }
  };

  const handleCloseSession = async () => {
    try {
      await apiPost('/api/v1/sessions/close', { session_id: sessionId }, initData);
    } catch {
      // ignore
    }
    onNewReading();
  };

  return (
    <div className="chat">
      <div className="cards-info">
        <div className="card-thumbs">
          {cards.map((card, i) => (
            <div key={i} className="card-thumb">
              <img src={getCardImage(card)} alt={getCardName(card)} />
            </div>
          ))}
        </div>
        <p>{cards.map(getCardName).join(' · ')}</p>
      </div>

      <div className="messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role} ${i === messages.length - 1 && loading ? 'streaming-cursor' : ''}`}>
            {msg.content || <span className="spinner" />}
          </div>
        ))}
        {messages.length === 0 && !loading && (
          <div className="message assistant">
            Задайте вопрос картам...
          </div>
        )}
      </div>

      <div className="input-area">
        <button className="new-reading-btn" onClick={handleCloseSession} disabled={loading}>
          Новый расклад
        </button>
        <div className="input-row">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Задайте вопрос..."
            disabled={loading}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          />
          <button onClick={handleSend} disabled={loading || !question.trim()}>
            {loading ? '...' : '→'}
          </button>
        </div>
      </div>
    </div>
  );
}
