import "server-only";
import { cache } from "react";

export const publicAnalyst = cache(async (token: string) => {
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) return null;
  const response = await fetch(`${process.env.API_URL || "http://localhost:8000"}/api/public/analyst/${token}`, { cache: "no-store", redirect: "error", signal: AbortSignal.timeout(10000) });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("The shared recap could not be loaded.");
  return response.json() as Promise<{
    season: number; week: number; league_name: string; generated_at: string;
    markdown: string; revision: number; correction_note: string | null;
  }>;
});
