import { OwnerPopulation } from "@/lib/owner-membership";

export function OwnerPopulationControl({ value, onChange }: {
  value: OwnerPopulation; onChange: (value: OwnerPopulation) => void;
}) {
  return <label className="flex flex-wrap items-center gap-2 text-figure text-dim my-2">
    Owners
    <select aria-label="Owner population" value={value}
      onChange={(event) => onChange(event.target.value as OwnerPopulation)}
      className="bg-transparent text-ink border border-rule rounded px-2 py-1">
      <option value="current">Current owners</option>
      <option value="all">All owners · includes former</option>
    </select>
  </label>;
}
