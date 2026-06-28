import { useChatStore } from './store';

type WsPayload =
  | { type: 'hitl_request'; request_id: string; tool: string; args: Record<string, unknown>; reason: string }
  | { type: 'hitl_decision'; request_id: string; status: 'approved' | 'denied'; tool: string; args: Record<string, unknown>; reason: string }
  | { type: 'guardrail'; layer?: string; action: string; reason: string; tool?: string }
  | { type: 'error'; message: string }
  | { type: 'pong' };

class SessionWebSocketClient {
  private socket: WebSocket | null = null;
  private sessionId: string | null = null;

  connect(sessionId: string) {
    if (this.sessionId === sessionId && this.socket) return;
    this.disconnect();

    const url = this.buildUrl(sessionId);
    this.sessionId = sessionId;
    this.socket = new WebSocket(url);
    this.socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as WsPayload;
        this.handlePayload(payload);
      } catch (error) {
        console.error('WS payload parse failed', error);
      }
    };
    this.socket.onclose = () => {
      this.socket = null;
      this.sessionId = null;
    };
  }

  disconnect() {
    if (this.socket) this.socket.close();
    this.socket = null;
    this.sessionId = null;
  }

  approve(requestId: string) {
    this.send({ action: 'approve', request_id: requestId });
  }

  deny(requestId: string) {
    this.send({ action: 'deny', request_id: requestId });
  }

  private send(payload: Record<string, unknown>) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify(payload));
  }

  private handlePayload(payload: WsPayload) {
    const store = useChatStore.getState();
    if (payload.type === 'hitl_request') {
      store.addHitlRequest({
        requestId: payload.request_id,
        tool: payload.tool,
        args: payload.args,
        reason: payload.reason,
        status: 'pending',
      });
      return;
    }
    if (payload.type === 'hitl_decision') {
      store.resolveHitlRequest(payload.request_id, payload.status);
      return;
    }
    if (payload.type === 'guardrail') {
      store.addGuardrail({
        action: payload.action,
        reason: payload.reason,
        tool: payload.tool,
      });
    }
  }

  private buildUrl(sessionId: string) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const port = window.location.port === '3000' ? '8000' : window.location.port;
    const host = `${window.location.hostname}${port ? `:${port}` : ''}`;
    return `${protocol}//${host}/api/chat/sessions/${sessionId}/ws`;
  }
}

export const sessionWsClient = new SessionWebSocketClient();
