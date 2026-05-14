// ─────────────────────────────────────────────────────────────────────────────
// Albedo server configuration
// Replace YOUR_TAILSCALE_IP with the Tailscale IP shown by `tailscale ip -4`
// on the machine running server.py  (e.g. 100.64.0.1)
// ─────────────────────────────────────────────────────────────────────────────
export const SERVER_BASE = 'http://YOUR_TAILSCALE_IP:8000';

// ── Response shapes (mirror server.py Pydantic models) ───────────────────────

export interface ChatResponse {
  text: string;
  audio_b64: string | null;
  verify_protocol: boolean;
}

export interface VoiceResponse {
  transcript: string;
  text: string;
  audio_b64: string | null;
  verify_protocol: boolean;
}

export interface StatusResponse {
  status: string;
  llm_model: string;
  whisper_model: string;
  whisper_device: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function assertOk(response: Response): Promise<void> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore parse errors */
    }
    throw new Error(detail);
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * POST /api/chat — send a text message, receive text + optional base64 WAV.
 */
export async function chatRequest(
  text: string,
  useWeb = false,
): Promise<ChatResponse> {
  const response = await fetch(`${SERVER_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, use_web: useWeb }),
  });
  await assertOk(response);
  return response.json() as Promise<ChatResponse>;
}

/**
 * POST /api/voice — upload a recorded audio file, receive transcript + text + optional base64 WAV.
 *
 * @param audioUri  Local file URI returned by expo-av's Recording.getURI()
 */
export async function voiceRequest(audioUri: string): Promise<VoiceResponse> {
  const ext = (audioUri.split('.').pop() ?? 'wav').toLowerCase();
  const mimeMap: Record<string, string> = {
    wav:  'audio/wav',
    m4a:  'audio/m4a',
    aac:  'audio/aac',
    mp4:  'audio/mp4',
    '3gp':'audio/3gpp',
    webm: 'audio/webm',
  };
  const mimeType = mimeMap[ext] ?? 'audio/wav';

  const formData = new FormData();
  formData.append('file', {
    uri: audioUri,
    type: mimeType,
    name: `recording.${ext}`,
  } as unknown as Blob);

  const response = await fetch(`${SERVER_BASE}/api/voice`, {
    method: 'POST',
    body: formData,
    // Do NOT set Content-Type manually — fetch sets it with the multipart boundary
  });
  await assertOk(response);
  return response.json() as Promise<VoiceResponse>;
}

/**
 * GET /api/status — lightweight health check.
 * Returns true if the server is reachable and online.
 */
export async function serverStatus(): Promise<StatusResponse | null> {
  try {
    const response = await fetch(`${SERVER_BASE}/api/status`, {
      method: 'GET',
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) return null;
    return response.json() as Promise<StatusResponse>;
  } catch {
    return null;
  }
}
