/* ---------------------------------------------------------------------------
 * Agate — the coverage note. `DashboardResp.warnings` carries the backend's
 * disclosures about what the numbers on this page can and cannot see (today:
 * a redraft league's thin value coverage and its unvalued draft picks — see
 * grader_io.pull_supporting_data). It shipped as dead data: nothing in web/
 * read the field, so a redraft owner saw a 2027 1st priced at 0 with no
 * explanation anywhere on the page.
 *
 * Set as a section, not an alert: a mono kicker on a hairline, then one muted
 * line per note (DESIGN.md § "Depth" — a section is a heading over a hairline,
 * then content). No banner, no icon, no colored fill; a disclosure is not a
 * failure, and a colored word would be a lie. Deliberately NOT on a `.ruled`
 * ground: these are sentences, and prose on the 26px pitch has to truncate,
 * which would hide the very thing the note exists to say.
 *
 * Absence, not an empty state — no notes renders nothing at all.
 * ------------------------------------------------------------------------ */

export function LeagueNotes({ notes }: { notes?: string[] | null }) {
  if (!notes || notes.length === 0) return null;

  return (
    <section className="mt-4" aria-label="Coverage notes">
      <div className="border-b border-rule pb-1.5">
        <span className="font-mono text-label uppercase tracking-[0.16em] text-dim">
          Coverage
        </span>
      </div>
      {notes.map((note) => (
        <p key={note} className="mt-1.5 max-w-[72ch] text-figure leading-relaxed text-dim">
          {note}
        </p>
      ))}
    </section>
  );
}
