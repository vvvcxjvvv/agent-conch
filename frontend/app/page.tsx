'use client';

import { useState } from 'react';
import Sidebar from '@/components/chat/Sidebar';
import Conversation from '@/components/chat/Conversation';
import MetricsPanel from '@/components/metrics/MetricsPanel';

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [profile, setProfile] = useState('user-chat-v1');

  return (
    <div className="three-col-grid">
      {/* 左栏：会话列表 + Profile 选择器 */}
      <Sidebar
        currentSessionId={sessionId}
        onSelectSession={setSessionId}
        selectedProfile={profile}
        onSelectProfile={setProfile}
      />

      {/* 中栏：对话区 */}
      <main className="flex flex-col h-full bg-white">
        <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h1 className="text-sm font-semibold text-gray-700">
            {sessionId ? `会话 ${sessionId.slice(0, 8)}` : 'AgentConch'}
          </h1>
          <span className="text-xs text-gray-400">{profile}</span>
        </header>
        <Conversation sessionId={sessionId} profile={profile} />
      </main>

      {/* 右栏：实时指标 */}
      <MetricsPanel />
    </div>
  );
}
