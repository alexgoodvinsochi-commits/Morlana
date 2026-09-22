import { useState, useEffect, useRef } from 'react';
import { useReadingSession } from '../hooks/useReadingSession';
import '../styles/reading.css';

interface Props {
  initData: string;
  onExit: () => void;
  onHistory: () => void;
  /* Открыто кнопкой «Новый расклад»: начинаем с нуля, не продолжая прошлый. */
  startFresh?: boolean;
}

/* Только представление: весь HTTP, возобновление и опрос живут в
   useReadingSession, здесь остаётся вёрстка и черновик вопроса. */
export default function ReadingScreen({ initData, onExit, onHistory, startFresh = false }: Props) {
  const {
    reading,
    loading,
    error,
    streamText,
    synthesisText,
    interpretFailed,
    ask,
    draw,
    nextCycle,
    restart,
    interpret,
    synthesize,
    dismissError,
  } = useReadingSession(initData, startFresh);

  const [question, setQuestion] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const interpretationRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [reading, streamText, synthesisText]);

  useEffect(() => {
    const scroll = interpretationRef.current;
    if (scroll) {
      scroll.scrollTop = scroll.scrollHeight;
    }
  }, [streamText, synthesisText]);

  const handleAsk = async () => {
    if (await ask(question)) {
      setQuestion('');
    }
  };

  const handleNewReading = async () => {
    setQuestion('');
    await restart();
  };

  if (!reading && !error) {
    return (
      <div className="reading-screen">
        <div className="reading-loading">
          <span className="spinner" /> Загрузка...
        </div>
      </div>
    );
  }

  if (error && !reading) {
    return (
      <div className="reading-screen">
        <div className="error-msg">
          <p>{error}</p>
          <button onClick={handleNewReading} disabled={loading} aria-busy={loading}>
            Начать заново
          </button>
        </div>
      </div>
    );
  }

  if (!reading) return null;

  const progress = Math.round((reading.cycle_count / reading.max_cycles) * 100);
  const cards = reading.current_cards;

  return (
    <div className="reading-screen">
      {/* Card Container - 3/4 screen */}
      <div className="card-container">
        {cards.length > 0 ? (
          <>
            {cards.map((card) => {
              const name = card.reversed ? `${card.name} (перевёрнута)` : card.name;
              return (
                <div className="current-card" key={`${card.position}-${card.card_id}`}>
                  <img src={card.image} alt={name} className="current-card-image" />
                  <p className="current-card-name">{name}</p>
                </div>
              );
            })}
          </>
        ) : reading.current_question ? (
          <p className="current-question">Ваш вопрос: {reading.current_question}</p>
        ) : (
          <h2>Цикл {reading.cycle_count + 1}/{reading.max_cycles}</h2>
        )}
      </div>

      {/* Dots Indicator */}
      {cards.length > 0 && (
        <div className="dots-indicator">
          <div className="dot active" />
          <div className="dot" />
          <div className="dot" />
        </div>
      )}

      {/* Scrollable Interpretation */}
      {(streamText || synthesisText) && (
        <div className="interpretation-container">
          <div className="interpretation-gradient-top" />
          <div className="interpretation-scroll" ref={interpretationRef}>
            {synthesisText && (
              <div className="synthesis-text">
                <h3>Итоговая синтезация</h3>
                <p>{synthesisText}</p>
              </div>
            )}
            {streamText && (
              <div className="interpretation-text">
                <p>{streamText}</p>
              </div>
            )}
          </div>
          <div className="interpretation-gradient-bottom" />
        </div>
      )}

      {/* Action Buttons */}
      <div className="reading-actions">
        {reading.state === 'WAITING' && (
          <div className="input-row">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Задайте вопрос картам..."
              disabled={loading}
              onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
            />
            <button
              onClick={handleAsk}
              disabled={loading || !question.trim()}
              aria-busy={loading}
            >
              {loading ? '...' : '→'}
            </button>
          </div>
        )}

        {reading.state === 'QUESTION_ASKED' && (
          <button onClick={draw} disabled={loading} aria-busy={loading}>
            {loading ? <><span className="spinner" /> Вытягиваю...</> : 'Вытянуть карту'}
          </button>
        )}

        {reading.state === 'CARDS_DRAWN' && (
          <button onClick={interpret} disabled={loading} aria-busy={loading}>
            {loading ? <><span className="spinner" /> Толкую...</> : 'Получить толкование'}
          </button>
        )}

        {reading.state === 'INTERPRETATION' && (
          interpretFailed ? (
            <div className="interpret-retry">
              {!error && <p className="reading-status">Толкование не пришло.</p>}
              <button onClick={interpret} disabled={loading} aria-busy={loading}>
                {loading ? <><span className="spinner" /> Толкую...</> : 'Повторить толкование'}
              </button>
            </div>
          ) : (
            <div className="reading-status">
              <span className="spinner" /> Толкование загружается...
            </div>
          )
        )}

        {(reading.state === 'READY' || reading.state === 'COMPLETED') && (
          <div className="cycle-complete-actions">
            {reading.cycle_count < reading.max_cycles && reading.state === 'READY' && (
              <button onClick={nextCycle} disabled={loading} aria-busy={loading}>
                Следующий цикл
              </button>
            )}
            {!synthesisText && (
              <button
                onClick={synthesize}
                disabled={loading}
                aria-busy={loading}
                className="synthesis-btn"
              >
                {loading ? <><span className="spinner" /> Синтезирую...</> : 'Синтезировать расклад'}
              </button>
            )}
          </div>
        )}

        {reading.state === 'COMPLETED' && (
          <div className="reading-complete-actions">
            <button onClick={handleNewReading} disabled={loading} aria-busy={loading}>
              Новый расклад
            </button>
            <button onClick={onHistory}>Мои расклады</button>
            <button onClick={onExit} className="exit-btn">На главную</button>
          </div>
        )}
      </div>

      {/* Progress Bar */}
      <div className="reading-progress">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <p className="progress-text">
          Цикл {reading.cycle_count} из {reading.max_cycles}
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="error-msg">
          <p>{error}</p>
          <button onClick={dismissError}>Закрыть</button>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
}
