'use client';

import { ShieldAlert, Check, X } from 'lucide-react';
import { HitlRequest } from '@/lib/store';
import { sessionWsClient } from '@/lib/ws-client';

interface HitlApprovalPanelProps {
  requests: HitlRequest[];
}

export default function HitlApprovalPanel({ requests }: HitlApprovalPanelProps) {
  const pending = requests.filter((r) => r.status === 'pending');
  if (pending.length === 0) return null;

  return (
    <div className="space-y-2 px-4">
      {pending.map((request) => (
        <div
          key={request.requestId}
          className="rounded-md border border-amber-200 bg-amber-50 p-3"
        >
          <div className="flex items-start gap-2">
            <ShieldAlert className="mt-0.5 h-4 w-4 text-amber-600" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-amber-900">
                待审批工具：{request.tool}
              </p>
              <p className="mt-1 text-xs text-amber-800">{request.reason}</p>
              <pre className="mt-2 overflow-x-auto rounded bg-white/70 p-2 text-xs text-amber-900">
                {JSON.stringify(request.args, null, 2)}
              </pre>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => sessionWsClient.approve(request.requestId)}
                  className="inline-flex items-center gap-1 rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700"
                >
                  <Check className="h-3.5 w-3.5" />
                  批准并恢复
                </button>
                <button
                  onClick={() => sessionWsClient.deny(request.requestId)}
                  className="inline-flex items-center gap-1 rounded-md bg-gray-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
                >
                  <X className="h-3.5 w-3.5" />
                  拒绝
                </button>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
