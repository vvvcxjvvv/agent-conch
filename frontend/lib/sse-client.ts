import { useChatStore } from './store';

const API_BASE = '/api';

interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
}

/** 解析 SSE 流，逐事件回调 */
async function parseSSE(
  response: Response,
  onEvent: (evt: SSEEvent) => void
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    let currentEvent = '';
    let currentData = '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        currentData = line.slice(6);
      } else if (line === '' && currentEvent) {
        try {
          const data = JSON.parse(currentData);
          onEvent({ event: currentEvent, data });
        } catch {
          // 忽略解析失败的事件
        }
        currentEvent = '';
        currentData = '';
      }
    }
  }
}

/** 发送聊天消息，流式接收 SSE 响应 */
export async function streamChat(
  sessionId: string,
  message: string,
  profile: string,
  onEvent?: (evt: SSEEvent) => void
): Promise<void> {
  const store = useChatStore.getState();
  store.startStreaming(message);

  const response = await fetch(`${API_BASE}/chat/sessions/${sessionId}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, profile }),
  });

  if (!response.ok) {
    store.finishStreaming(false);
    throw new Error(`Stream failed: ${response.status}`);
  }

  await parseSSE(response, (evt) => {
    const { event, data } = evt;
    const d = data as Record<string, unknown>;

    switch (event) {
      case 'text_delta':
        store.appendTextDelta(d.content as string);
        break;
      case 'tool_call':
        store.addToolCall(
          d.tool as string,
          d.args as Record<string, unknown>,
          d.call_id as string
        );
        break;
      case 'tool_result':
        if (d.call_id) {
          store.updateToolResult(d.call_id as string, d.result as string);
        } else {
          // 按 tool 名匹配最近的未完成调用
          store.updateToolResult(
            useChatStore.getState().toolCalls.slice(-1)[0]?.callId || '',
            d.result as string
          );
        }
        break;
      case 'guardrail':
        store.addGuardrail({
          action: d.action as string,
          reason: d.reason as string,
          tool: d.tool as string | undefined,
        });
        break;
      case 'cost_update':
        store.updateMetrics({
          tokens: d.tokens as number,
          cost: d.cost as number,
          steps: d.steps as number,
        });
        break;
      case 'done':
        store.finishStreaming(d.success as boolean);
        break;
    }
    onEvent?.(evt);
  });
}
