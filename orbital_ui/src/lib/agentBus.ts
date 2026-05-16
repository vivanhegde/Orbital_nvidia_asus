/** Shape accepted by POST /api/agent/event and yielded by GET /api/agent/stream SSE lines. */

export interface AgentBusEvent {
  type: string;
  content: string;
  related_event_id: string | null;
  timestamp: string;
  source?: string;
}
