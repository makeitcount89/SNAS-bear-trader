import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SNAS Bear Trader",
  description:
    "Selective, cash-default bear-market rotation dashboard for SNAS.AX on the ASX — sibling to LNAS-SNAS",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[var(--page-plane)] font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
