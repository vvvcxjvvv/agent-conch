import { create } from 'zustand';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: ToolCall[];
}

export interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
  result?: string;
  callId: string;
  durationMs?: number;
}

export interface Metrics {
  tokens: number;
  cost: number;
  steps: number;
}

export interface GuardrailEvent {
  action: string;
  reason: string;
  tool?: string;
}

export interface HitlRequest {
  requestId: string;
  tool: string;
  args: Record<string, unknown>;
  reason: string;
  status: 'pending' | 'approved' | 'denied';
}

interface ChatState {
  messages: Message[];
  toolCalls: ToolCall[];
  metrics: Metrics;
  guardrailEvents: GuardrailEvent[];
  hitlRequests: HitlRequest[];
  status: 'idle' | 'streaming' | 'done' | 'error';
  currentAssistantMsg: string;
  lastUserMessage: string;
  retryRequestId: string | null;

  appendTextDelta: (content: string) => void;
  addToolCall: (tool: string, args: Record<string, unknown>, callId: string) => void;
  updateToolResult: (callId: string, result: string) => void;
  updateMetrics: (metrics: Partial<Metrics>) => void;
  addGuardrail: (event: GuardrailEvent) => void;
  addHitlRequest: (request: Omit<HitlRequest, 'status'> & { status?: HitlRequest['status'] }) => void;
  resolveHitlRequest: (requestId: string, status: HitlRequest['status']) => void;
  clearRetryRequest: () => void;
  startStreaming: (userMessage: string) => void;
  startResumeStreaming: () => void;
  finishStreaming: (success: boolean) => void;
  reset: () => void;
}

const genId = () => Math.random().toString(36).slice(2, 10);

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  toolCalls: [],
  metrics: { tokens: 0, cost: 0, steps: 0 },
  guardrailEvents: [],
  hitlRequests: [],
  status: 'idle',
  currentAssistantMsg: '',
  lastUserMessage: '',
  retryRequestId: null,

  appendTextDelta: (content) =>
    set((s) => ({
      currentAssistantMsg: s.currentAssistantMsg + content,
      status: 'streaming',
    })),

  addToolCall: (tool, args, callId) =>
    set((s) => ({
      toolCalls: [...s.toolCalls, { tool, args, callId }],
    })),

  updateToolResult: (callId, result) =>
    set((s) => ({
      toolCalls: s.toolCalls.map((tc) =>
        tc.callId === callId ? { ...tc, result } : tc
      ),
    })),

  updateMetrics: (m) =>
    set((s) => ({ metrics: { ...s.metrics, ...m } })),

  addGuardrail: (event) =>
    set((s) => ({ guardrailEvents: [...s.guardrailEvents, event] })),

  addHitlRequest: (request) =>
    set((s) => {
      const next = {
        requestId: request.requestId,
        tool: request.tool,
        args: request.args,
        reason: request.reason,
        status: request.status ?? 'pending',
      };
      const existing = s.hitlRequests.find((r) => r.requestId === next.requestId);
      return {
        hitlRequests: existing
          ? s.hitlRequests.map((r) => (r.requestId === next.requestId ? { ...r, ...next } : r))
          : [...s.hitlRequests, next],
      };
    }),

  resolveHitlRequest: (requestId, status) =>
    set((s) => ({
      hitlRequests: s.hitlRequests.map((r) =>
        r.requestId === requestId ? { ...r, status } : r
      ),
      retryRequestId: status === 'approved' ? requestId : s.retryRequestId,
    })),

  clearRetryRequest: () => set({ retryRequestId: null }),

  startStreaming: (userMessage) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: genId(), role: 'user', content: userMessage },
      ],
      currentAssistantMsg: '',
      status: 'streaming',
      guardrailEvents: [],
      lastUserMessage: userMessage,
    })),

  startResumeStreaming: () =>
    set((s) => ({
      currentAssistantMsg: '',
      status: 'streaming',
      guardrailEvents: [],
      retryRequestId: null,
      lastUserMessage: s.lastUserMessage,
    })),

  finishStreaming: (success) =>
    set((s) => {
      const nextMessages =
        s.currentAssistantMsg.trim().length > 0
          ? [
              ...s.messages,
              {
                id: genId(),
                role: 'assistant' as const,
                content: s.currentAssistantMsg,
                toolCalls: s.toolCalls.filter(
                  (tc) => !s.messages.some((m) => m.toolCalls?.some((mc) => mc.callId === tc.callId))
                ),
              },
            ]
          : s.messages;
      return {
        messages: nextMessages,
        currentAssistantMsg: '',
        status: success ? 'done' : 'error',
      };
    }),

  reset: () =>
    set({
      messages: [],
      toolCalls: [],
      metrics: { tokens: 0, cost: 0, steps: 0 },
      guardrailEvents: [],
      hitlRequests: [],
      status: 'idle',
      currentAssistantMsg: '',
      lastUserMessage: '',
      retryRequestId: null,
    }),
}));
