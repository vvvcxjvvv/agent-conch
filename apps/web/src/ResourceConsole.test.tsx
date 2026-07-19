import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResourceConsole } from "./App";

describe("ResourceConsole", () => {
  it("renders session, tool, MCP, Skill and Hook resources", () => {
    const select = vi.fn();
    const refresh = vi.fn();
    render(
      <ResourceConsole
        sessions={[{ id: "session-1", status: "completed", updated_at: 1, cwd: "/tmp" }]}
        messages={[{ id: 1, session_id: "session-1", role: "assistant", content: "done", created_at: 1 }]}
        tools={{ schemas: [{ name: "bash", description: "shell", parameters: {} }], health: { bash: { suppressed: false } } }}
        skills={[{ name: "review", description: "Review code", path: "/skills/review" }]}
        mcp={[{ name: "files", enabled: true, connected: true, error: "", tools: [{}] }]}
        hooks={[{ execution_id: "hook-1", hook_name: "quality", status: "passed", event: "graph_end" }]}
        selectedSession="session-1"
        onSelectSession={select}
        onRefreshMcp={refresh}
      />,
    );
    expect(screen.getByText("bash")).toBeInTheDocument();
    expect(screen.getByText("Review code")).toBeInTheDocument();
    expect(screen.getByText("connected")).toBeInTheDocument();
    expect(screen.getByText("quality")).toBeInTheDocument();
    fireEvent.click(screen.getByText("刷新 MCP"));
    expect(refresh).toHaveBeenCalledOnce();
  });
});
