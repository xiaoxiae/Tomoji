const API_BASE = '/api';

export class RateLimitError extends Error {
  constructor(message: string = 'Too many requests. Please wait a moment and try again.') {
    super(message);
    this.name = 'RateLimitError';
  }
}

async function handleResponse<T>(res: Response, errorMessage: string): Promise<T> {
  if (res.status === 429) {
    throw new RateLimitError();
  }
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || errorMessage);
  }
  return res.json();
}

export interface Emoji {
  emoji: string;
  codepoint: string;
  name: string;
}

export interface EmojiCategory {
  id: string;
  name: string;
  emojis: Emoji[];
}

export interface EmojisResponse {
  categories: EmojiCategory[];
}

export interface CapturedEmoji {
  emoji: string;
  codepoint: string;
  image_data: string;  // base64 data URL
  custom?: boolean;
}

export interface CaptureParams {
  image: string;
  padding?: number;
  keep_background?: boolean;
  keep_clothes?: boolean;
  keep_accessories?: boolean;
}

export interface ExportResult {
  success: boolean;
  captured_count: number;
  total_emojis: number;
  font_url: string;
  last_generation: string;
}

export interface Settings {
  padding: number;
  keep_background: boolean;
  keep_clothes: boolean;
  keep_accessories: boolean;
}

export interface SessionResponse {
  session_id: string;
}

export interface SessionValidation {
  valid: boolean;
  session_id: string;
}

// ============================================================
// Session Management (no session required)
// ============================================================

export async function createSession(): Promise<SessionResponse> {
  const res = await fetch(`${API_BASE}/session`, {
    method: 'POST',
  });
  return handleResponse(res, 'Failed to create session');
}

export async function validateSession(sessionId: string): Promise<SessionValidation> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/validate`);
  return handleResponse(res, 'Failed to validate session');
}

// ============================================================
// Global Endpoints (no session required)
// ============================================================

export async function listEmojis(): Promise<EmojisResponse> {
  const res = await fetch(`${API_BASE}/emojis`);
  if (!res.ok) throw new Error('Failed to fetch emojis');
  return res.json();
}

// ============================================================
// Session-Scoped Endpoints
// ============================================================

export interface GalleryResponse {
  captured: CapturedEmoji[];
  total: number;
  custom_emojis: Emoji[];
  last_capture_edit: string | null;
  last_generation: string | null;
}

export async function getGallery(sessionId: string): Promise<GalleryResponse> {
  const res = await fetch(`${API_BASE}/${sessionId}/gallery`);
  if (!res.ok) throw new Error('Failed to fetch gallery');
  return res.json();
}

export async function previewCapture(
  sessionId: string,
  emoji: string,
  params: CaptureParams
): Promise<{ success: boolean; emoji: string; codepoint: string; preview_image: string }> {
  const res = await fetch(`${API_BASE}/${sessionId}/capture/${encodeURIComponent(emoji)}/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Preview failed');
  }
  return res.json();
}

export async function saveCapture(
  sessionId: string,
  emoji: string,
  image: string
): Promise<{ success: boolean; emoji: string; codepoint: string; capture_url: string }> {
  const res = await fetch(`${API_BASE}/${sessionId}/capture/${encodeURIComponent(emoji)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Save failed');
  }
  return res.json();
}

export async function deleteCapture(sessionId: string, emoji: string): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/${sessionId}/capture/${encodeURIComponent(emoji)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to delete capture');
  return res.json();
}

export async function clearSession(sessionId: string): Promise<{ success: boolean; deleted_count: number }> {
  const res = await fetch(`${API_BASE}/${sessionId}/captures`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to clear session');
  return res.json();
}

export async function exportFont(sessionId: string, fontName: string = 'Tomoji'): Promise<ExportResult> {
  const res = await fetch(`${API_BASE}/${sessionId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ font_name: fontName }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || 'Export failed');
  }
  return res.json();
}

export function getFontUrl(sessionId: string): string {
  return `${API_BASE}/${sessionId}/font.woff2`;
}

export function getImagesZipUrl(sessionId: string, name?: string): string {
  const base = `${API_BASE}/${sessionId}/images.zip`;
  if (name) {
    return `${base}?name=${encodeURIComponent(name)}`;
  }
  return base;
}

export async function getSettings(sessionId: string): Promise<Settings> {
  const res = await fetch(`${API_BASE}/${sessionId}/settings`);
  if (!res.ok) throw new Error('Failed to fetch settings');
  return res.json();
}

export async function saveSettings(sessionId: string, settings: Settings): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/${sessionId}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error('Failed to save settings');
  return res.json();
}
