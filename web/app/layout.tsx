import "./globals.css";
// Side-effect import (server-only): registers the backend-token provider so RSC
// fetches in lib/api attach an Authorization header. Must run before any RSC
// data fetch; the root layout is the earliest server module in every route.
import "@/lib/auth-server";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import localFont from "next/font/local";
import { SessionProvider } from "next-auth/react";
import { ThemeProvider } from "@/components/ThemeProvider";
import { Telemetry } from "@/components/Telemetry";
import { PRODUCT_NAME } from "@/lib/brand";

/* Bricolage Grotesque is the display face — nameplates, section headings,
 * franchise and player names. It replaced Archivo, which is gone: Archivo 900
 * uppercase carried the broadsheet voice that read as shouting at consumer
 * scale (`.design/tokens/typography.css`).
 *
 * Self-hosted from the design system, and the VARIABLE build deliberately.
 * Bricolage's `opsz` axis redraws the letterforms for the size they are set at,
 * tightening spacing and thinning joins as size rises. A static instance
 * freezes opsz at 14 — and this system runs from `--text-label` at 8.5px to
 * `--nameplate-1` at 44px, so it spans the whole axis the variable build exists
 * for. `font-weight: 200 800` is a RANGE, so 700 (`--weight-heading`) and 800
 * (`--weight-display`) both come out of this one file; never add a second face
 * for another weight.
 *
 * Only the `latin` build is listed. `next/font/local`'s `src` entries carry no
 * `unicode-range`, so adding `latin-ext` here would declare two @font-face
 * rules with identical descriptors and the later one would win outright for
 * basic latin too. The design system's own `tokens/fonts.css` (imported by
 * globals.css) declares both builds WITH their ranges under the real family
 * name, so `tailwind.config.ts` chains `font-display` to
 * `"Bricolage Grotesque"` behind this variable — that is where an accented
 * franchise name gets its glyph. */
const bricolage = localFont({
  src: "../../.design/assets/fonts/bricolage-grotesque-latin-var.woff2",
  weight: "200 800",
  style: "normal",
  display: "swap",
  variable: "--font-bricolage",
});

export const metadata = {
  // Resolves OG/Twitter image URLs against the real public domain (AUTH_URL),
  // not localhost. Falls back to localhost for dev.
  metadataBase: new URL(process.env.AUTH_URL || "http://localhost:3000"),
  // Default tab title is the product name; pages that set their own title
  // (league, owner, trade) render as "<their title> · Fantasy Analyzer".
  // This was "FFB Dynasty" — a THIRD name, alongside "dynasty.report" in the
  // strip and "Fantasy Analyzer" in the design system.
  // Read from `lib/brand`, never restated. These were two more hardcoded
  // literals of the product name, which is how the app came to carry three at
  // once; the same habit left `e2e/landing.spec.ts` asserting "dynasty.report"
  // for weeks after the rename.
  title: {
    default: PRODUCT_NAME,
    template: `%s · ${PRODUCT_NAME}`,
  },
  // What Google prints under the title and what a shared link unfurls with —
  // the one line of copy that reaches people who have never opened the app.
  // It said "Sleeper dynasty trade grader": a retired name, and an undersell of
  // a product that now grades drafts and rates franchises too.
  description: "Grade every trade, draft, and franchise in your dynasty league.",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover" as const,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} ${bricolage.variable}`}
    >
      <body>
        <SessionProvider>
          <ThemeProvider>
            <Telemetry />
            {children}
          </ThemeProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
