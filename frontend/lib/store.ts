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

interface ChatState {
  messages: Message[];
  toolCalls: ToolCall[];
  metrics: Metrics;
  guardrailEvents: GuardrailEvent[];
  status: 'idle' | 'streaming' | 'done' | 'error';
  currentAssistantMsg: string;

  appendTextDelta: (content: string) => void;
  addToolCall: (tool: string, args: Record<string, unknown>, callId: string) => void;
  updateToolResult: (callId: string, result: string) => void;
  updateMetrics: (metrics: Partial<Metrics>) => void;
  addGuardrail: (event: GuardrailEvent) => void;
  startStreaming: (userMessage: string) => void;
  finishStreaming: (success: boolean) => void;
  reset: () => void;
}

const genId = () => Math.random().toString(36).slice(2, 10);

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  toolCalls: [],
  metrics: { tokens: 0, cost: 0, steps: 0 },
  guardrailEvents: [],
  status: 'idle',
  currentAssistantMsg: '',

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

  startStreaming: (userMessage) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: genId(), role: 'user', content: userMessage },
      ],
      currentAssistantMsg: '',
      status: 'streaming',
      guardrailEvents: [],
    })),

  finishStreaming: (success) =>
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id: genId(),
          role: 'assistant',
          content: s.currentAssistantMsg,
          toolCalls: s.toolCalls.filter((tc) => !s.messages.some((m) => m.toolCalls?.some((mc) => mc.callId === tc.callId))),
        },
      ],
      currentAssistantMsg: '',
      status: success ? 'done' : 'error',
    })),

  reset: () =>
    set({
      messages: [],
      toolCalls: [],
      metrics: { tokens: 0, cost: 0, steps: 0 },
      guardrailEvents: [],
      status: 'idle',
      currentAssistantMsg: '',
    }),
}));
