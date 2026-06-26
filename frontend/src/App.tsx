import { useState, useEffect } from 'react';
import { useTelegram } from './hooks/useTelegram';
import Onboarding from './components/Onboarding';
import Greeting from './components/Greeting';
import TarotDraw from './components/TarotDraw';
import Chat from './components/Chat';

type Screen = 'onboarding' | 'greeting' | 'draw' | 'chat';

interface UserData {
  zodiac_sign: string;
  greeting: string;
  free_requests_left: number;
}

interface AppState {
  screen: Screen;
  userData: UserData | null;
  sessionId: string;
  layoutType: string;
  cards: number[];
}

const STORAGE_KEY = 'morlana_state';

function loadState(): AppState | null {
  if (new URLSearchParams(window.location.search).get('reset') === '1') {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function saveState(state: AppState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

function App() {
  const { initData } = useTelegram();
  const [state, setState] = useState<AppState>(() => {
    const saved = loadState();
    const skipOnboarding = import.meta.env.VITE_SKIP_ONBOARDING === 'true';
    return saved || {
      screen: skipOnboarding ? 'draw' : 'onboarding',
      userData: null,
      sessionId: crypto.randomUUID(),
      layoutType: '3_cards',
      cards: [],
    };
  });

  useEffect(() => {
    saveState(state);
  }, [state]);

  const handleOnboardingComplete = (data: UserData) => {
    setState((prev) => ({ ...prev, userData: data, screen: 'greeting' }));
  };

  const handleGreetingNext = () => {
    setState((prev) => ({ ...prev, screen: 'draw' }));
  };

  const handleDraw = async (drawnCards: number[], type: string) => {
    setState((prev) => ({
      ...prev,
      cards: drawnCards,
      layoutType: type,
      screen: 'chat',
    }));
  };

  const handleNewReading = () => {
    setState({
      screen: 'draw',
      userData: state.userData,
      sessionId: crypto.randomUUID(),
      layoutType: '3_cards',
      cards: [],
    });
  };

  return (
    <div className="app">
      {state.screen === 'onboarding' && (
        <Onboarding initData={initData} onComplete={handleOnboardingComplete} />
      )}

      {state.screen === 'greeting' && state.userData && (
        <Greeting
          zodiacSign={state.userData.zodiac_sign}
          greeting={state.userData.greeting}
          onNext={handleGreetingNext}
        />
      )}

      {state.screen === 'draw' && (
        <TarotDraw initData={initData} onDraw={handleDraw} />
      )}

      {state.screen === 'chat' && (
        <Chat
          initData={initData}
          sessionId={state.sessionId}
          layoutType={state.layoutType}
          cards={state.cards}
          onNewReading={handleNewReading}
        />
      )}
    </div>
  );
}

export default App;
