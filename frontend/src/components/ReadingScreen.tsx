import { useState, useEffect, useRef } from 'react';
import { apiGet } from '../api/client';
import type { ReadingStateResponse } from '../api/client';
import { useReadingSession } from '../hooks/useReadingSession';
import '../styles/reading.css';

interface Props {
  initData: string;
  onExit: () => void;
  onHistory: () => void;
  /* Открыто кнопкой «Новый расклад»: начинаем с нуля, не продолжая прошлый. */
  startFresh?: boolean;
}

/* Ответ GET /api/v1/tarot/decks: картинку рубашки знает только сервер. */
interface DeckInfo {
  id: string;
  name: string;
  back_image: string;
}

/* Рубашки колод за сеанс не меняются: спрашиваем их один раз на всё
   приложение, повторные экраны берут готовый ответ. */
let deckBacksRequest: Promise<Record<string, string>> | null = null;

function loadDeckBacks(initData: string): Promise<Record<string, string>> {
  if (!deckBacksRequest) {
    deckBacksRequest = apiGet<DeckInfo[]>('/api/v1/tarot/decks', initData)
      .then((decks) => Object.fromEntries(decks.map((deck) => [deck.id, deck.back_image])))
      .catch((err) => {
        /* Неудачу не кешируем: следующий расклад попробует ещё раз. */
        deckBacksRequest = null;
        throw err;
      });
  }
  return deckBacksRequest;
}

/* Номер цикла, которому принадлежат лежащие на экране карты. После толкования
   cycle_count уже вырос, а карта осталась той же, поэтому «до толкования» и
   «после» должны давать одно число: иначе появление карты играло бы дважды. */
function cardCycleNumber(reading: ReadingStateResponse): number {
  const interpreted = reading.state === 'READY' || reading.state === 'COMPLETED';
  return interpreted ? reading.cycle_count : reading.cycle_count + 1;
}

/* Почти только представление: весь HTTP расклада, возобновление и опрос живут
   в useReadingSession, здесь остаётся вёрстка, черновик вопроса и рубашка
   колоды — она нужна одной лишь анимации появления карты. */
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
  /* Рубашка колоды этого расклада: с ней карта появляется рубашкой вверх и
     переворачивается, без неё — сразу лицом, как раньше. */
  const [deckBack, setDeckBack] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const interpretationRef = useRef<HTMLDivElement>(null);
  /* Выкладка, которая уже показалась лицом (рубашка пришла позже): задним
     числом её не переворачиваем. */
  const shownFaceRef = useRef('');

  /* Читатель сам внизу блока толкования — только тогда идём за текстом. */
  const atBottomRef = useRef(false);
  /* Предыдущие значения текстов: по переходу «пусто -> текст» видно, что
     начался новый ответ, и его надо показать с первой строки. Храним их, а не
     флаг «идёт поток»: между вопросами блок толкования исчезает со страницы,
     и флаг, завязанный на этот блок, не успевал сброситься. */
  const prevStreamRef = useRef('');
  const prevSynthesisRef = useRef('');

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [reading?.state]);

  useEffect(() => {
    const startedInterpretation = !!streamText && !prevStreamRef.current;
    const startedSynthesis = !!synthesisText && !prevSynthesisRef.current;
    prevStreamRef.current = streamText;
    prevSynthesisRef.current = synthesisText;

    const scroll = interpretationRef.current;
    if (!scroll) return;
    if (startedInterpretation || startedSynthesis) {
      atBottomRef.current = false;
      scroll.scrollTop = 0;
      return;
    }
    if (atBottomRef.current) {
      scroll.scrollTop = scroll.scrollHeight;
    }
  }, [streamText, synthesisText]);

  const deckId = reading?.deck_id ?? '';
  /* Один ключ на всю выкладку: меняется только с новыми картами, поэтому
     появление играется у каждой новой карты и ни разу внутри цикла. */
  const drawKey = reading && reading.current_cards.length > 0
    ? `${cardCycleNumber(reading)}-${reading.current_cards.map((card) => card.card_id).join('-')}`
    : '';

  useEffect(() => {
    if (!initData || !deckId) return;
    let cancelled = false;

    loadDeckBacks(initData)
      .then((backs) => {
        const back = backs[deckId] ?? '';
        if (cancelled) return;
        if (!back) {
          setDeckBack('');
          return;
        }
        /* Рубашка идёт в дело только когда картинка уже в кэше браузера: иначе
           вместо неё проявилась бы пустая рамка, а битый файл крутил бы пустоту.
           Не загрузилась — анимации просто нет, карта показывается лицом. */
        const preload = new Image();
        preload.onload = () => {
          if (!cancelled) setDeckBack(back);
        };
        preload.onerror = () => {
          if (!cancelled) setDeckBack('');
        };
        preload.src = back;
      })
      .catch(() => {
        /* Анимация необязательна: расклад из-за неё не встаёт. */
      });

    return () => {
      cancelled = true;
    };
  }, [initData, deckId]);

  useEffect(() => {
    if (drawKey && !deckBack) {
      shownFaceRef.current = drawKey;
    }
  }, [drawKey, deckBack]);

  const revealCard = !!drawKey && !!deckBack && shownFaceRef.current !== drawKey;

  const handleInterpretationScroll = () => {
    const scroll = interpretationRef.current;
    if (!scroll) return;
    atBottomRef.current = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 24;
  };

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
    <div className={reading.state === 'COMPLETED' ? 'reading-screen reading-screen--completed' : 'reading-screen'}>
      {/* Card Container - 3/4 screen */}
      <div className="card-container">
        {cards.length > 0 ? (
          <>
            {cards.map((card) => {
              const name = card.reversed ? `${card.name} (перевёрнута)` : card.name;
              return (
                <div
                  className={revealCard ? 'current-card current-card--reveal' : 'current-card'}
                  key={`${drawKey}-${card.position}`}
                >
                  <div className="card-flip">
                    <div className="card-flip-inner">
                      {revealCard && (
                        <img src={deckBack} alt="" className="current-card-image card-flip-back" />
                      )}
                      <img src={card.image} alt={name} className="current-card-image card-flip-front" />
                    </div>
                  </div>
                  <p className="current-card-name">{name}</p>
                </div>
              );
            })}
          </>
        ) : reading.current_question ? (
          <p className="current-question">Ваш вопрос: {reading.current_question}</p>
        ) : (
          <h2>Вопрос {reading.cycle_count + 1} из {reading.max_cycles}</h2>
        )}
      </div>

      {/* Индикатор карт вернётся вместе с раскладами из нескольких карт. */}

      {/* Scrollable Interpretation */}
      {(streamText || synthesisText) && (
        <div className="interpretation-container">
          <div className="interpretation-gradient-top" />
          <div
            className="interpretation-scroll"
            ref={interpretationRef}
            onScroll={handleInterpretationScroll}
          >
            {synthesisText && (
              <div className="synthesis-text">
                <h3>Итог расклада</h3>
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
            {loading ? <><span className="spinner" /> Раскладываю карты...</> : 'Получить толкование'}
          </button>
        )}

        {reading.state === 'INTERPRETATION' && (
          interpretFailed ? (
            <div className="interpret-retry">
              {!error && <p className="reading-status">Толкование не пришло.</p>}
              <button onClick={interpret} disabled={loading} aria-busy={loading}>
                {loading ? <><span className="spinner" /> Раскладываю карты...</> : 'Повторить толкование'}
              </button>
            </div>
          ) : (
            <div className="reading-status">
              <span className="spinner" /> Раскладываю карты...
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
                {loading ? <><span className="spinner" /> Подвожу итог...</> : 'Подвести итог'}
              </button>
            )}
          </div>
        )}

        {reading.state === 'COMPLETED' && (
          <div className="reading-complete-actions">
            <button
              onClick={handleNewReading}
              disabled={loading}
              aria-busy={loading}
              className="restart-btn"
            >
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
          Вопрос {reading.cycle_count} из {reading.max_cycles}
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
