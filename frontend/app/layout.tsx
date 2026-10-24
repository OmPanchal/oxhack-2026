import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Compute Arbitrage Engine", description: "Buy-side compute scheduling terminal" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
