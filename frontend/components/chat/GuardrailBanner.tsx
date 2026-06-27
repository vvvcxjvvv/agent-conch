'use client';

import { AlertTriangle, X } from 'lucide-react';
import { useState } from 'react';
import { GuardrailEvent } from '@/lib/store';

interface GuardrailBannerProps {
  events: GuardrailEvent[];
}

export default function GuardrailBanner({ events }: GuardrailBannerProps) {
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  const visible = events.filter((_, i) => !dismissed.has(i));

  if (visible.length === 0) return null;

  return (
    <div className="mb-2 space-y-1">
      {events.map((event, i) => (
        !dismissed.has(i) && (
          <div
            key={i}
            className="flex items-center gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-md text-sm text-amber-800"
          >
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span className="flex-1">
              {event.tool && <strong>{event.tool}: </strong>}
              {event.reason || `护栏${event.action === 'blocked' ? '拦截' : '警告'}`}
            </span>
            <button
              onClick={() => setDismissed((prev) => new Set(prev).add(i))}
              className="text-amber-400 hover:text-amber-600"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )
      ))}
    </div>
  );
}
