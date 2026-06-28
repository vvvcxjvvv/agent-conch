'use client';

import { useEffect } from 'react';
import { useChatStore } from '@/lib/store';
import { resumeChat } from '@/lib/sse-client';
import { sessionWsClient } from '@/lib/ws-client';
import MessageList from './MessageList';
import InputBox from './InputBox';

interface ConversationProps {
  sessionId: string | null;
  profile: string;
}

export default function Conversation({ sessionId, profile }: ConversationProps) {
  const retryRequestId = useChatStore((s) => s.retryRequestId);
  const clearRetryRequest = useChatStore((s) => s.clearRetryRequest);
  const status = useChatStore((s) => s.status);

  useEffect(() => {
    if (!sessionId) {
      sessionWsClient.disconnect();
      return;
    }
    sessionWsClient.connect(sessionId);
    return () => {
      sessionWsClient.disconnect();
    };
  }, [sessionId]);

  useEffect(() => {
    if (!retryRequestId || !sessionId || status === 'streaming') return;
    clearRetryRequest();
    resumeChat(sessionId, retryRequestId).catch((error) => {
      console.error('Resume stream error:', error);
    });
  }, [retryRequestId, sessionId, profile, status, clearRetryRequest]);

  return (
    <div className="flex flex-col h-full">
      <MessageList />
      <InputBox sessionId={sessionId} profile={profile} />
    </div>
  );
}
