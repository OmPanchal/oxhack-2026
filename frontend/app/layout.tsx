import type { Metadata } from "next";
import localFont from "next/font/local";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "./globals.css";
const brokenPixels = localFont({
  src: "./fonts/BrokenPixels-Regular.ttf",
  variable: "--font-broken-pixels",
  weight: "400",
  style: "normal",
  display: "swap",
});
export const metadata: Metadata = { title: "Arbitr", description: "Buy-side compute scheduling terminal" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body className={brokenPixels.variable}>{children}</body></html>;
}
