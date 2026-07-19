import { expect, test } from "@playwright/test";

test("opens the resource console and loads backend resources", async ({ page }) => {
  await page.route("http://127.0.0.1:8765/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload: Record<string, unknown> = {
      "/sessions": [{ id: "e2e-session", status: "completed", updated_at: 1, cwd: "/tmp" }],
      "/tools": { schemas: [{ name: "bash", description: "shell", parameters: {} }], health: { bash: { suppressed: false } } },
      "/skills": [{ name: "review", description: "Review code", path: "/skills/review" }],
      "/mcp/servers": [{ name: "files", enabled: true, connected: true, error: "", tools: [] }],
      "/hooks/executions": [],
      "/insights": { sessions: 1, success_rate: 1, total_tokens: 10, tool_calls: 1, average_tool_duration_ms: 2 },
      "/governance/overview": { policy: { approval_level: 4, roles: {}, rules: [] }, approvals: [], budgets: [], credentials: [], regressions: { cases: 0, latest_results: [] }, schedules: [], coordinator: [], snapshots: [] },
      "/approvals": [],
      "/security/audit": [],
    };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload[path] ?? []) });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "资源控制台" }).first().click();
  await expect(page.getByText("会话与消息")).toBeVisible();
  await expect(page.getByText("bash")).toBeVisible();
  await expect(page.getByText("Review code")).toBeVisible();
});
