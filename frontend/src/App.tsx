import { useState, useEffect } from 'react';
import { useTelegram } from './hooks/useTelegram';
import Onboarding from './components/Onboarding';
import LoginScreen from './components/LoginScreen';
import UserDashboard from './components/UserDashboard';
import ReadingScreen from './components/ReadingScreen';
import ReadingHistory from './components/ReadingHistory';
import BottomNav from './components/BottomNav';

type Screen = 'login' | 'onboarding' | 'dashboard' | 'reading' | 'history';

interface AppState {
  screen: Screen;
  userLogin: string | null;
  userName: string | null;
}

const STORAGE_KEY = 'morlana_state';

const VALID_SCREENS: Screen[] = ['login', 'onboarding', 'dashboard'];

function loadState(): AppState | null {
  if (new URLSearchParams(window.location.search).get('reset') === '1') {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !VALID_SCREENS.includes(parsed.screen)) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
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
    return saved || { screen: 'login', userLogin: null, userName: null };
  });

  useEffect(() => {
    saveState(state);
  }, [state]);

  const handleLogin = (data: { login: string; real_name: string }) => {
    setState({ screen: 'dashboard', userLogin: data.login, userName: data.real_name });
  };

  const handleRegister = () => {
    setState((prev) => ({ ...prev, screen: 'onboarding' }));
  };

  const handleOnboardingComplete = (data: { login: string; real_name: string }) => {
    setState({ screen: 'dashboard', userLogin: data.login, userName: data.real_name });
  };

  const handleLogout = () => {
    localStorage.removeItem(STORAGE_KEY);
    setState({ screen: 'login', userLogin: null, userName: null });
  };

  const handleNavigate = (screen: 'home' | 'reading' | 'history') => {
    if (screen === 'home') {
      setState((prev) => ({ ...prev, screen: 'dashboard' }));
    } else if (screen === 'reading') {
      setState((prev) => ({ ...prev, screen: 'reading' }));
    } else if (screen === 'history') {
      setState((prev) => ({ ...prev, screen: 'history' }));
    }
  };

  const handleExitReading = () => {
    setState((prev) => ({ ...prev, screen: 'dashboard' }));
  };

  const showNav = state.screen === 'dashboard' || state.screen === 'reading' || state.screen === 'history';
  const navScreen = state.screen === 'dashboard' ? 'home' : state.screen as 'reading' | 'history';

  return (
    <div className="app">
      <div className="app-content">
        {state.screen === 'login' && (
          <LoginScreen onLogin={handleLogin} onRegister={handleRegister} />
        )}

        {state.screen === 'onboarding' && (
          <Onboarding initData={initData} onComplete={handleOnboardingComplete} />
        )}

        {state.screen === 'dashboard' && state.userLogin && (
          <UserDashboard
            initData={initData}
            userLogin={state.userLogin}
            onLogout={handleLogout}
            onNewReading={() => handleNavigate('reading')}
          />
        )}

        {state.screen === 'reading' && (
          <ReadingScreen initData={initData} onExit={handleExitReading} />
        )}

        {state.screen === 'history' && (
          <ReadingHistory initData={initData} onBack={() => handleNavigate('home')} />
        )}
      </div>

      {showNav && (
        <BottomNav active={navScreen} onNavigate={handleNavigate} />
      )}
    </div>
  );
}

export default App;
