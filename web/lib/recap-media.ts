export type RecapMediaInfo = {
  id: string;
  duration_seconds: number;
  video_bytes: number;
  audio_bytes: number;
};

export function recapMediaBase(token: string, bundle: string) {
  return `/api/public/analyst/${encodeURIComponent(token)}/media/${encodeURIComponent(bundle)}`;
}
