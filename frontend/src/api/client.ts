const API_BASE = import.meta.env.VITE_API_URL || '';

export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(status: number, detail?: string) {
    super(`API error: ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function buildUrl(path: string): string {
  const base = API_BASE ? API_BASE.replace(/\/$/, '') : window.location.origin;
  const sep = path.startsWith('/') ? '' : '/';
  return base + sep + path;
}

function buildHeaders(initData?: string): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) {
    headers['Authorization'] = `Bearer ${initData}`;
  }
  return headers;
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail: string | undefined;
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string') {
      detail = body.detail;
    }
  } catch {
    // body is missing or not JSON — status alone describes the error
  }
  return new ApiError(res.status, detail);
}

export async function apiPost<T>(path: string, body: Record<string, unknown>, initData?: string): Promise<T> {
  const url = buildUrl(path);

  const res = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(initData),
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    throw await toApiError(res);
  }

  return res.json();
}

export async function apiGet<T>(path: string, initData?: string): Promise<T> {
  const url = buildUrl(path);

  const res = await fetch(url, {
    headers: buildHeaders(initData),
  });

  if (!res.ok) {
    throw await toApiError(res);
  }

  return res.json();
}

export async function apiStream(
  path: string,
  body: Record<string, unknown>,
  initData: string,
  onChunk: (text: string) => void,
  onDone: () => void,
  onCleaned?: (text: string) => void,
): Promise<void> {
  const url = buildUrl(path);

  const res = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(initData),
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    throw await toApiError(res);
  }

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      if (buffer.startsWith('data: ')) {
        const data = buffer.slice(6);
        if (data === '[DONE]') {
          onDone();
          return;
        }
        try {
          const parsed = JSON.parse(data);
          if (parsed.cleaned && onCleaned) {
            onCleaned(parsed.cleaned);
          } else if (parsed.text) {
            onChunk(parsed.text);
          }
        } catch {}
      }
      onDone();
      return;
    }

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
          if (parsed.cleaned && onCleaned) {
            onCleaned(parsed.cleaned);
          } else if (parsed.text) {
            onChunk(parsed.text);
          }
        } catch {}
      }
    }
  }
}
