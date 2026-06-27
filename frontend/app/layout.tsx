import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AgentConch',
  description: 'Agent Harness Engineering 平台',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh">
      <body className="antialiased">{children}</body>
    </html>
  );
}
