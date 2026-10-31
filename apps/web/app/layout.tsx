import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "Cardio Research Records",
  description: "Local verified-record workflow (Milestones 1-2).",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main>{children}</main>
        <footer>
          Local-only build. A research tool, not medical advice: it drafts questions and protocols but prescribes
          nothing, orders no tests and starts no experiment. A laboratory flag is not a diagnosis.
        </footer>
      </body>
    </html>
  );
}
