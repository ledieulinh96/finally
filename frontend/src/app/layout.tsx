import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FinAlly — AI trading workstation",
  description: "Live KOSPI/KOSDAQ prices, a simulated portfolio and an AI trading copilot.",
};

export const viewport: Viewport = { themeColor: "#0e1320" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
