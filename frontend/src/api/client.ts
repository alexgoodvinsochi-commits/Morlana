const API_BASE = import.meta.env.VITE_API_URL || '';

function buildUrl(path: string, initData?: string): string {
  const base = API_BASE ? API_BASE.replace(/\/$/, '') : window.location.origin;
  const sep = path.startsWith('/') ? '' : '/';
  let url = base + sep + path;
  if (initData) {
    url += (url.includes('?') ? '&' : '?') + 'initData=' + encodeURIComponent(initData);
  }
  return url;
}

export async function apiPost<T>(path: string, body: Record<string, unknown>, initData?: string): Promise<T> {
  const url = buildUrl(path, initData);

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (res.status === 402) {
    throw new Error('PAYWALL');
  }

  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }

  return res.json();
}

export async function apiGet<T>(path: string, initData?: string): Promise<T> {
  const url = buildUrl(path, initData);

  const res = await fetch(url);

  if (res.status === 402) {
    throw new Error('PAYWALL');
  }

  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }

  return res.json();
}

export async function apiStream(
  path: string,
  body: Record<string, unknown>,
  initData: string,
  onChunk: (text: string) => void,
  onDone: () => void,
): Promise<void> {
  const url = buildUrl(path, initData);

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (res.status === 402) {
    throw new Error('PAYWALL');
  }

  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') {
          onDone();
          return;
        }
        try {
          const parsed = JSON.parse(data);
          onChunk(parsed.text);
        } catch {}
      }
    }
  }
}
