import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    // The zero-radius override is GONE. Agate had no radius anywhere, so a
    // top-level `borderRadius` map pinned every utility to 0 and made a stray
    // `rounded-lg` inert. Furniture has a shape vocabulary — 16px on panels,
    // 8px on controls, a pill on segmented controls — so the scale resolves
    // normally again and the drift guard asserts the sanctioned values instead
    // of banning the property (`tests/furniture-rules.test.ts`, rule `radius`).
    extend: {
      fontFamily: {
        // Bricolage Grotesque carries nameplates, section headings, franchise
        // and player names. Geist carries prose and controls; Geist Mono
        // carries every figure.
        //
        // Two entries, both Bricolage: the first is the `next/font/local`
        // variable from `app/layout.tsx` (latin, preloaded, self-hosted); the
        // second is the real family name declared by the design system's
        // `tokens/fonts.css`, which ships latin AND latin-ext with correct
        // `unicode-range`s. An accented name falls through to it rather than to
        // system-ui.
        display: ["var(--font-bricolage)", "Bricolage Grotesque"],
        sans: ["var(--font-geist-sans)"],
        mono: ["var(--font-geist-mono)"],
      },
      colors: {
        bg: "var(--bg)",
        // Furniture's panel ground. Agate had no surface — rows sat on the
        // striped page — so these three are new and are what a Panel is made of.
        surface: "var(--surface)",
        "surface-sunk": "var(--surface-sunk)",
        paper: "var(--paper)",
        "rule-lit": "var(--rule-lit)",
        rule: "var(--rule)",
        "rule-strong": "var(--rule-strong)",
        dim: "var(--dim)",
        body: "var(--body)",
        ink: "var(--ink)",
        pos: "var(--pos)",
        neg: "var(--neg)",
        // The -strong halves are for text/glyphs ON a wash or tint, where the
        // base tone drops below AA. Never for a row figure.
        "pos-strong": "var(--pos-strong)",
        "neg-strong": "var(--neg-strong)",
        warn: "var(--warn)",
        "warn-strong": "var(--warn-strong)",
        "pos-wash": "var(--pos-wash)",
        "neg-wash": "var(--neg-wash)",
        "warn-wash": "var(--warn-wash)",
        // Bars are a THIRD pair, weight-matched so neither hue reads as "more"
        // at equal length. Do not point these at --pos/--neg.
        "pos-bar": "var(--pos-bar)",
        "neg-bar": "var(--neg-bar)",
        stamp: "var(--stamp)",
        "stamp-ink": "var(--stamp-ink)",
        "stamp-ink-dim": "var(--stamp-ink-dim)",
        "stamp-deep": "var(--stamp-deep)",
        "stamp-lit": "var(--stamp-lit)",
        "stamp-rule": "var(--stamp-rule)",
        "stamp-wash": "var(--stamp-wash)",
        "stamp-strong": "var(--stamp-strong)",
        ringfocus: "var(--ringfocus)",
      },
      // Named, not numbered, so the drift guard can allow exactly these three
      // and still fail a stray `rounded-lg` or `rounded-[10px]`.
      borderRadius: {
        panel: "var(--radius)",
        sm: "var(--radius-sm)",
        pill: "var(--radius-pill)",
      },
      boxShadow: {
        panel: "var(--shadow)",
      },
      fontSize: {
        nameplate: "var(--text-nameplate)",
        lead: "var(--text-lead)",
        section: "var(--text-section)",
        name: "var(--text-name)",
        // `prose`, not `body`: `text-body` already resolves to the --body COLOR,
        // and a fontSize key of the same name would make that utility ambiguous
        // and silently change every existing `text-body` call site.
        prose: "var(--text-body)",
        figure: "var(--text-figure)",
        label: "var(--text-label)",
      },
      spacing: {
        // One ledger entry. Row heights and plot heights are multiples of this.
        rule: "var(--rule-pitch)",
      },
      minHeight: {
        // The design system owns the value (`--tap-min`); this only names it.
        tap: "var(--tap-min)",
      },
    },
  },
  plugins: [],
};

export default config;
