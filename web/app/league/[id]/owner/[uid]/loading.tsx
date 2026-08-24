// Route-level skeleton shown while the owner page's server fetch runs —
// without it the arrival path is a blank screen. Mirrors the real layout (top
// bar, back link, hero band with letter + rings, tab bar, content) so nothing
// shifts when data lands.
//
// Furniture — "The Ground Loads First". Same layout, square `--rule` bars, no
// striped ground: the rings strip mirrors HeroBand's RingsStrip, which sits
// inside a Panel around a plain grid (not a Row — a strip wraps onto however
// many lines it needs, unlike a ledger entry). The content placeholder is a
// Panel of Rows, each drawing its own `--rule` hairline. The view-wide pulse
// animation stays retired; the only motion is the single IndeterminateBar at
// the foot ("One Thing Moves" — one per view).
import { Shell } from "@/components/Shell";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { IndeterminateBar } from "@/components/furniture/IndeterminateBar";

function Bar({ className = "" }: { className?: string }) {
  return <div className={`bg-rule ${className}`} />;
}

export default function OwnerLoading() {
  return (
    <Shell>
      {/* The announcement lives OUTSIDE the aria-busy subtree — aria-busy tells
          AT to ignore that subtree, which would swallow a live region inside it. */}
      <p aria-live="polite" className="sr-only">Loading franchise…</p>
      <div aria-busy="true">
        {/* Top bar stand-in (the real TopBar renders with the page) */}
        <div className="mb-6 flex items-center justify-between border-b border-rule pb-4" aria-hidden="true">
          <div className="flex items-center gap-6">
            <Bar className="h-[9px] w-20" />
            <Bar className="h-[9px] w-12" />
            <Bar className="h-[9px] w-16" />
          </div>
          <Bar className="h-[9px] w-16" />
        </div>

        <section className="mt-2">
          {/* ← All owners */}
          <Bar className="h-[9px] w-20" />

          {/* Hero band: name + big letter over the rings strip */}
          <div className="mt-5">
            <div className="flex items-start justify-between gap-5">
              <div className="min-w-0">
                <Bar className="h-[28px] w-52 min-[701px]:h-[44px]" />
                <Bar className="mt-2 h-[9px] w-32" />
              </div>
              <Bar className="h-[34px] w-14 shrink-0 min-[701px]:h-[46px]" />
            </div>
            <div className="mt-3.5">
              {/* Same shape as RingsStrip/StatStrip (ownerdeepdive/ui.tsx):
                  a Panel around a plain grid, not a Row — the strip is not a
                  ledger entry with a column contract. */}
              <Panel>
                <div className="grid grid-cols-2 gap-x-5 gap-y-2.5 px-3.5 py-3 min-[701px]:grid-cols-4">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Bar key={i} className="h-[9px] w-full max-w-[80px]" />
                  ))}
                </div>
              </Panel>
            </div>
          </div>

          {/* Tab bar */}
          <div className="mt-6 flex h-[44px] items-center gap-5 border-b border-rule">
            {Array.from({ length: 4 }).map((_, i) => (
              <Bar key={i} className="h-[9px] w-16" />
            ))}
          </div>

          {/* Content — a Panel of placeholder rows, each drawing its own
              --rule hairline (a solid Panel has no stripe to divide them). */}
          <Panel className="mt-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <Row key={i} className="grid-cols-[1fr_auto]">
                <Bar className="h-[9px] w-full max-w-[220px]" />
                <Bar className="h-[9px] w-14" />
              </Row>
            ))}
          </Panel>

          {/* The one animated element in this view. */}
          <div className="mt-6">
            <IndeterminateBar label="Loading franchise" />
          </div>
        </section>
      </div>
    </Shell>
  );
}
