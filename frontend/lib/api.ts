/**
 * The only file that talks to the backend over HTTP. Both calls return the
 * same PipelineResponse shape, so callers don't need to know which
 * endpoint they hit.
 */
import type { PipelineResponse, Selection } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function parseResponse(res: Response): Promise<PipelineResponse> {
  if (!res.ok) {
    // The backend's exception handler returns {detail: "..."} on failure.
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${res.status})`);
  }
  return res.json();
}

/** Build the URL for a Google Places photo.
 *
 *  Routed through the backend on purpose: Places photo URLs require the
 *  Maps API key, so constructing them here would expose it in the browser.
 *  The frontend only ever handles the opaque `photo_ref`. */
export function photoUrl(ref: string, width = 640): string {
  return `${API_BASE}/photo?ref=${encodeURIComponent(ref)}&w=${width}`;
}

export function startTrip(message: string): Promise<PipelineResponse> {
  return fetch(`${API_BASE}/trips`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  }).then(parseResponse);
}

export function sendMessage(
  threadId: string,
  message: string,
  selection?: Selection
): Promise<PipelineResponse> {
  return fetch(`${API_BASE}/trips/${threadId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, selection: selection ?? null }),
  }).then(parseResponse);
}
