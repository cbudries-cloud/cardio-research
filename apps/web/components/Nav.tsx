"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/ask", label: "Ask" },
  { href: "/research", label: "Research" },
  { href: "/next", label: "Next" },
  { href: "/context", label: "Health context" },
  { href: "/documents", label: "Records" },
  { href: "/review", label: "Review queue" },
  { href: "/trends", label: "Trends" },
  { href: "/baseline", label: "Baseline" },
  { href: "/investigation", label: "ApoB / LDL-P" },
];

export function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <header className="top">
      <span className="brand">Cardio Research</span>
      <nav>
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={active(l.href) ? "active" : ""}>
            {l.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
