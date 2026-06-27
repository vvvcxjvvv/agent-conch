'use client';

import { useChatStore } from '@/lib/store';
import MessageList from './MessageList';
import InputBox from './InputBox';

interface ConversationProps {
  sessionId: string | null;
  profile: string;
}

export default function Conversation({ sessionId, profile }: ConversationProps) {
  return (
    <div className="flex flex-col h-full">
      <MessageList />
      <InputBox sessionId={sessionId} profile={profile} />
    </div>
  );
}
