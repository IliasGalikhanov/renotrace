// Only user-initiated loads retry. No polling, warm-up or keepalive traffic.
const ATTEMPTS = 4;
const RETRY_DELAY_MS = 20_000;
const ATTEMPT_TIMEOUT_MS = 25_000;

function pause(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    signal.throwIfAborted();
    const cancel = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve();
    }, RETRY_DELAY_MS);
    signal.addEventListener("abort", cancel, { once: true });
  });
}

export async function requestDemo(
  url: string,
  init: RequestInit,
  signal: AbortSignal,
  onRetry?: (attempt: number) => void,
): Promise<Response> {
  for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
    signal.throwIfAborted();
    try {
      const response = await fetch(url, {
        ...init,
        signal: AbortSignal.any([
          signal,
          AbortSignal.timeout(ATTEMPT_TIMEOUT_MS),
        ]),
      });
      if (![502, 503, 504].includes(response.status)) return response;
      await response.body?.cancel();
    } catch {
      signal.throwIfAborted();
    }
    if (attempt === ATTEMPTS) break;
    onRetry?.(attempt + 1);
    await pause(signal);
  }
  throw new Error(
    "The demo service hasn't responded yet. Please retry in a moment.",
  );
}
