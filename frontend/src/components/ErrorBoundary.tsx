import { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="app" style={{ padding: '40px 20px', textAlign: 'center' }}>
          <h2 style={{ color: '#ffd700', marginBottom: '16px' }}>Что-то пошло не так</h2>
          <p style={{ color: '#b0b0b0', marginBottom: '24px' }}>
            {this.state.error?.message || 'Произошла непредвиденная ошибка'}
          </p>
          <button
            onClick={() => {
              localStorage.removeItem('morlana_state');
              window.location.reload();
            }}
          >
            Начать заново
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
