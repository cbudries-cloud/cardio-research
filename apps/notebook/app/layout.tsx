import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Research Notebook",
  description: "Source-verified evidence entries for a personal cardiovascular research project.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site">
          <Link href="/" className="brand">
            Research Notebook
          </Link>
          <nav>
            <Link href="/">Entries</Link>
            <Link href="/build">Build log</Link>
            <Link href="/methods">Methods</Link>
          </nav>
        </header>
        <main>{children}</main>
        <footer className="site">
          Published evidence only. This notebook contains no personal health records and makes no personal risk
          estimates or recommendations. Local preview; not published.
        </footer>
      </body>
    </html>
  );
}
