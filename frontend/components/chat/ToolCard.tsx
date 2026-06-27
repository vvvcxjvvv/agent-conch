'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, Wrench, Clock } from 'lucide-react';
import { ToolCall } from '@/lib/store';

interface ToolCardProps {
  toolCall: ToolCall;
}

export default function ToolCard({ toolCall }: ToolCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="my-2 border border-gray-200 rounded-md bg-gray-50 overflow-hidden">
      {/* 头部 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-100"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-400" />
        )}
        <Wrench className="w-4 h-4 text-blue-500" />
        <span className="text-sm font-medium text-gray-700">{toolCall.tool}</span>
        {toolCall.durationMs && (
          <span className="ml-auto flex items-center gap-1 text-xs text-gray-400">
            <Clock className="w-3 h-3" />
            {toolCall.durationMs}ms
          </span>
        )}
        {toolCall.result && (
          <span className="text-xs text-green-600">✓ 完成</span>
        )}
      </button>

      {/* 展开内容 */}
      {expanded && (
        <div className="border-t border-gray-200 px-3 py-2 text-xs">
          <div className="mb-2">
            <p className="font-mono text-gray-500 mb-1">参数:</p>
            <pre className="bg-white border border-gray-100 rounded p-2 overflow-x-auto">
              {JSON.stringify(toolCall.args, null, 2)}
            </pre>
          </div>
          {toolCall.result && (
            <div>
              <p className="font-mono text-gray-500 mb-1">结果:</p>
              <pre className="bg-white border border-gray-100 rounded p-2 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                {toolCall.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
