/** The mark: a route with three stops, the middle one open (the closure the platform works around). */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden>
      <rect width="40" height="40" rx="11" fill="var(--primary)" />
      <path d="M9 27c5 0 6-14 11-14s6 14 11 14" fill="none" stroke="white" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="9" cy="27" r="3.2" fill="white" />
      <circle cx="20" cy="13" r="3.2" fill="var(--primary)" stroke="white" strokeWidth="2.4" />
      <circle cx="31" cy="27" r="3.2" fill="white" />
    </svg>
  );
}
