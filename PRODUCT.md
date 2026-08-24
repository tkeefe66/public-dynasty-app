# Product

## Register

product

## Users

The ~10-12 managers of a single private Sleeper dynasty league who already know
each other. They show up mid-season and in the offseason to see where they
stand, to relitigate old trades, and to talk trash with receipts. They are not
strangers being onboarded cold; they know the league, the rivalries, and the
players. Context of use is a laptop or phone, often with the group chat open in
the other window.

## Product Purpose

An analysis layer over one dynasty league's entire history. It walks the league
chain back to its origin and grades every trade ever made through three lenses
side by side: **KTC** (today's market value), **production** (points actually
scored after the trade), and **impact** (realized, decisive usage). It also
tracks standings, owner careers, and per-season trade activity. Success is when
an argument in the group chat ends with someone pasting a link to this tool.

## Brand Personality

Sharp, candid, competitive. Two jobs at once: **settle the argument** (numbers
on the table, no hedging, drill into any claim) and **fuel the trash talk**
(this is a rivalry tool for friends, not a neutral SaaS report). Confident and
a little cocky, never corporate. Voice is an insider's, not an analyst briefing
strangers. Closest reference in feel: Linear / Vercel — fast, high-contrast,
monospace-accented, every element deliberate.

## Anti-references

- **ESPN / Yahoo fantasy:** cluttered, ad-stuffed, gradient-and-gloss mainstream
  fantasy UI. The opposite of what we want.
- **The Sleeper app itself:** this is a distinct analysis layer, not a reskin of
  Sleeper's own visual language. Don't borrow its look.
- **Generic SaaS dashboard:** card-grid + hero-metric template + purple
  gradient admin panel. Avoid the slop defaults.

## Design Principles

- **Receipts over opinions.** Every claim is backed by a number you can drill
  into. No assertion the data can't support.
- **Every lens, never one.** Always show the five metrics together — Trade Value,
  Total Points, Regular Season Points, Playoff Points, Toilet Bowl Points; the
  honesty of the grade is in seeing all of them, not cherry-picking the
  flattering one. (This principle predates the taxonomy and used to read "three
  lenses: KTC / production / impact". The vendor name is never rendered: it is
  **Trade Value**, always.)
- **Density without clutter.** Power-user data volume held to Linear/Vercel
  restraint — tabular, legible, fast. More signal, not more chrome.
- **Built for insiders.** The audience already knows the league. Skip
  cold-onboarding scaffolding; reward familiarity and reward exploration.

## Accessibility & Inclusion

Target WCAG AA: body text ≥4.5:1 contrast, large text ≥3:1, full keyboard
navigation, and a `prefers-reduced-motion` alternative for every animation.
Both light and dark themes must clear the bar. No known specialized user needs
in this league, so meet AA cleanly without over-investing beyond it.
