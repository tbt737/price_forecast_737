import type { Metadata } from "next";
import { themeNoFlashScript } from "@/app-layer/theme-toggle";
import { AppShell } from "@/widgets/app-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Multi-Commodity Quant Forecasting",
  description: "Generic, configuration-driven commodity forecasting platform — web frontend.",
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
