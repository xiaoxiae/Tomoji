const SESSION_COOKIE_NAME = 'tomoji_session';
const COOKIE_MAX_AGE = 7 * 24 * 60 * 60; // 7 days in seconds

export function getSessionCookie(): string | null {
  const match = document.cookie.match(new RegExp(`(^| )${SESSION_COOKIE_NAME}=([^;]+)`));
  return match ? match[2] : null;
}

export function setSessionCookie(sessionId: string): void {
  document.cookie = `${SESSION_COOKIE_NAME}=${sessionId}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`;
}

export function clearSessionCookie(): void {
  document.cookie = `${SESSION_COOKIE_NAME}=; path=/; max-age=0`;
}
