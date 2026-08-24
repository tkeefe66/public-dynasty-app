export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="max-w-[1180px] mx-auto px-3 sm:px-6 lg:px-8 py-6">
      <main>{children}</main>
    </div>
  );
}
