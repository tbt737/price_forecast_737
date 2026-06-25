import type { Metadata, Viewport } from "next";
import { themeNoFlashScript } from "@/app-layer/theme-toggle";
import { AppShell } from "@/widgets/app-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Multi-Commodity Quant Forecasting",
  description: "Generic, configuration-driven commodity forecasting platform — web frontend.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeNoFlashScript }} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
