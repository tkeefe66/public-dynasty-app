export type RecapMediaInfo = {
  id: string;
  duration_seconds: number;
  video_bytes: number;
  audio_bytes: number;
};

export type RecapVideoStatus = {
  status: "published" | "blocked" | "pending" | "disabled" | "unavailable";
  reason: string;
  message: string;
  enabled: boolean;
};

export function recapMediaBase(token: string, bundle: string) {
  return `/api/public/analyst/${encodeURIComponent(token)}/media/${encodeURIComponent(bundle)}`;
}
