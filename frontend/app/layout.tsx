import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI Assist for Travellers",
  description: "Plan and book a trip within your budget and dates.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/* suppressHydrationWarning: browser extensions (e.g. Grammarly) inject
          attributes like data-gr-ext-installed onto <body> before React
          hydrates, which otherwise trips a false-positive mismatch warning. */}
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
