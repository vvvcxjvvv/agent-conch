'use client';

import { useEffect, useRef } from 'react';
import { useChatStore } from '@/lib/store';
import ToolCard from './ToolCard';
import GuardrailBanner from './GuardrailBanner';

export default function MessageList() {
  const { messages, currentAssistantMsg, status, toolCalls, guardrailEvents } = useChatStore();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentAssistantMsg, messages.length]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      {messages.length === 0 && !currentAssistantMsg && (
        <div className="flex items-center justify-center h-full text-gray-400 text-sm">
          发送消息开始对话
        </div>
      )}

      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
        >
          <div
            className={`max-w-[80%] rounded-lg px-4 py-2 ${
              msg.role === 'user'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-800'
            }`}
          >
            <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
          </div>
        </div>
      ))}

      {/* 流式输出中的 assistant 消息 */}
      {currentAssistantMsg && (
        <div className="flex justify-start">
          <div className="max-w-[80%] rounded-lg px-4 py-2 bg-gray-100 text-gray-800">
            <p className="text-sm whitespace-pre-wrap">
              {currentAssistantMsg}
              {status === 'streaming' && (
                <span className="inline-block w-1.5 h-4 ml-0.5 bg-gray-400 animate-pulse" />
              )}
            </p>
          </div>
        </div>
      )}

      {/* 工具调用卡片 */}
      {toolCalls.length > 0 && (
        <div className="space-y-1">
          {toolCalls.map((tc, i) => (
            <ToolCard key={i} toolCall={tc} />
          ))}
        </div>
      )}

      {/* 护栏提示 */}
      <GuardrailBanner events={guardrailEvents} />

      <div ref={endRef} />
    </div>
  );
}
