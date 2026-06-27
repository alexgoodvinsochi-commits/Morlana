import { useState, useEffect } from 'react';
import { useTelegram } from './hooks/useTelegram';
import Onboarding from './components/Onboarding';
import Greeting from './components/Greeting';
import ReadingScreen from './components/ReadingScreen';

type Screen = 'onboarding' | 'greeting' | 'reading';

interface UserData {
  zodiac_sign: string;
  greeting: string;
  free_requests_left: number;
}

interface AppState {
  screen: Screen;
  userData: UserData | null;
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

const SKIP_ONBOARDING = import.meta.env.VITE_SKIP_ONBOARDING === 'true';

function App() {
  const { initData } = useTelegram();
  const [state, setState] = useState<AppState>(() => {
    const saved = loadState();
    return saved || {
      screen: SKIP_ONBOARDING ? 'reading' : 'onboarding',
      userData: null,
    };
  });

  useEffect(() => {
    saveState(state);
  }, [state]);

  const handleOnboardingComplete = (data: UserData) => {
    setState((prev) => ({ ...prev, userData: data, screen: 'greeting' }));
  };

  const handleGreetingNext = () => {
    setState((prev) => ({ ...prev, screen: 'reading' }));
  };

  const handleExitReading = () => {
    setState((prev) => ({ ...prev, screen: 'onboarding' }));
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

      {state.screen === 'reading' && (
        <ReadingScreen initData={initData} onExit={handleExitReading} />
      )}
    </div>
  );
}

export default App;
