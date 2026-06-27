'use client';

import { useState, KeyboardEvent } from 'react';
import { Send } from 'lucide-react';
import { useChatStore } from '@/lib/store';
import { streamChat } from '@/lib/sse-client';

interface InputBoxProps {
  sessionId: string | null;
  profile: string;
}

export default function InputBox({ sessionId, profile }: InputBoxProps) {
  const [input, setInput] = useState('');
  const status = useChatStore((s) => s.status);

  const handleSend = async () => {
    if (!input.trim() || !sessionId || status === 'streaming') return;

    const message = input;
    setInput('');

    try {
      await streamChat(sessionId, message, profile);
    } catch (e) {
      console.error('Stream error:', e);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const disabled = !sessionId || status === 'streaming';

  return (
    <div className="border-t border-gray-200 p-4">
      <div className="flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={sessionId ? '输入消息，Enter 发送，Shift+Enter 换行' : '请先创建会话'}
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none border border-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 max-h-32 disabled:bg-gray-50"
          style={{ minHeight: '40px' }}
        />
        <button
          onClick={handleSend}
          disabled={disabled || !input.trim()}
          className="flex items-center justify-center w-10 h-10 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
