import type { Comparison, CompareInput, Observation, ObservationInput, Preview, Project,
  ProjectDetail, Run, Scene, Summary, Task, TaskInput, Version, AgentResult, ModelStatus, ModelConnection, Clarifications } from "./types";

export class ApiError extends Error {
  constructor(public readonly code: string, message: string, public readonly requestId?: string) {
    super(message);
    this.name = "ApiError";
  }
}

type Session = { csrf_token: string };
type Envelope<T> = { request_id: string; data: T };

/** Cookies remain HttpOnly. CSRF stays in memory, never local/session storage. */
export class ApiClient {
  private csrf: string | undefined;
  private opening: Promise<void> | undefined;
  constructor(private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis)) {}

  private async decode<T>(response: Response): Promise<T> {
    let body: { data?: T; request_id?: string; error?: { code: string; message: string } };
    try {
      const parsed: unknown = await response.json();
      if (parsed === null || typeof parsed !== "object") throw new Error("not an envelope");
      body = parsed as typeof body;
    } catch {
      throw new ApiError("INVALID_RESPONSE", "暂时没有收到有效回复，请稍后重试。");
    }
    if (!response.ok) {
      if (response.status === 401 || body.error?.code === "CSRF_INVALID") this.csrf = undefined;
      throw new ApiError(body.error?.code ?? "REQUEST_FAILED",
        body.error?.message ?? "这次没有完成，请稍后重试。", body.request_id);
    }
    if (!("data" in body)) throw new ApiError("INVALID_RESPONSE", "返回的数据不完整。");
    return body.data as T;
  }

  private async session(): Promise<void> {
    if (this.csrf) return;
    if (!this.opening) {
      this.opening = (async () => {
        const response = await this.fetcher("/api/v1/session", { credentials: "include" });
        const session = await this.decode<Session>(response);
        if (!session || typeof session.csrf_token !== "string" || !session.csrf_token) {
          throw new ApiError("INVALID_RESPONSE", "没有取得有效会话，请稍后重试。");
        }
        this.csrf = session.csrf_token;
      })().finally(() => { this.opening = undefined; });
    }
    return this.opening;
  }

  private async request<T>(path: string, body?: unknown, key?: string,
    signal?: AbortSignal): Promise<T> {
    try { await this.session(); }
    catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError("NETWORK_UNAVAILABLE", "这次没连上。请检查连接后重试。");
    }
    const headers: Record<string, string> = {};
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      headers["X-CSRF-Token"] = this.csrf!;
      if (key) headers["Idempotency-Key"] = key;
    }
    const options: RequestInit = { method: body === undefined ? "GET" : "POST",
      credentials: "include", headers };
    if (body !== undefined) options.body = JSON.stringify(body);
    if (signal) options.signal = signal;
    try { return await this.decode<T>(await this.fetcher(`/api/v1${path}`, options)); }
    catch (error) {
      if (error instanceof ApiError || (error instanceof DOMException && error.name === "AbortError")) throw error;
      throw new ApiError("NETWORK_UNAVAILABLE", "这次没连上。已保存的方案不会被覆盖，请稍后重试。");
    }
  }

  projects(offset = 0) { return this.request<Project[]>(`/projects?limit=50&offset=${offset}`); }
  project(id: string) { return this.request<ProjectDetail>(`/projects/${encodeURIComponent(id)}`); }
  createProject(original_idea: string, title: string, key: string) {
    return this.request<Project>("/projects", { original_idea, title }, key);
  }
  confirm(id: string, scene: Scene, key: string) {
    return this.request<Version>(`/projects/${encodeURIComponent(id)}/scene-confirm`, { scene, confirmed: true }, key);
  }
  branch(id: string, scene: Scene, key: string) {
    return this.request<Version>(`/scene-versions/${encodeURIComponent(id)}/branches`, { scene, confirmed: true }, key);
  }
  preview(id: string, scene: Scene, scenario_label: string, signal: AbortSignal) {
    return this.request<Preview>(`/projects/${encodeURIComponent(id)}/preview`, { scene, scenario_label }, undefined, signal);
  }
  simulate(id: string, scenario_label: string, key: string) {
    return this.request<Run>(`/scene-versions/${encodeURIComponent(id)}/simulate`, { scenario_label }, key);
  }
  compare(id: string, body: CompareInput) {
    return this.request<Comparison>(`/projects/${encodeURIComponent(id)}/compare`, body);
  }
  summary(id: string) { return this.request<Summary>(`/projects/${encodeURIComponent(id)}/summary`); }
  createTask(id: string, body: TaskInput, key: string) {
    return this.request<Task>(`/projects/${encodeURIComponent(id)}/experiments`, body, key);
  }
  observe(id: string, body: ObservationInput, key: string) {
    return this.request<Observation>(`/experiments/${encodeURIComponent(id)}/observations`, body, key);
  }
  models() { return this.request<ModelStatus>("/models"); }
  connectModel(body: ModelConnection) { return this.request<ModelStatus>("/model-connection", body); }
  disconnectModel() { return this.request<ModelStatus>("/model-connection/disconnect", {}); }
  sceneDraft(id: string, key: string) { return this.request<AgentResult>(`/projects/${encodeURIComponent(id)}/scene-draft`, {}, key); }
  clarify(id: string, body: Clarifications, key: string) { return this.request<AgentResult>(`/projects/${encodeURIComponent(id)}/clarifications`, body, key); }
  confirmAgent(id: string, run_id: string, key: string) { return this.request<AgentResult>(`/projects/${encodeURIComponent(id)}/agent-confirm`, { run_id, confirmed: true }, key); }
  agent(id: string, runId: string) { return this.request<AgentResult>(`/projects/${encodeURIComponent(id)}/agent-runs/${encodeURIComponent(runId)}`); }
  analyze(id: string, version: string, scenario_label: string, key: string) { return this.request<AgentResult>(`/projects/${encodeURIComponent(id)}/agent-runs`, { scene_version_id: version, scenario_label }, key); }
  agentAction(id: string, runId: string, action_id: string, key: string) { return this.request<AgentResult>(`/projects/${encodeURIComponent(id)}/agent-runs/${encodeURIComponent(runId)}/actions`, { action_id, confirmed: true }, key); }
  retryAgent(id: string, run_id: string, key: string) { return this.request<AgentResult>(`/projects/${encodeURIComponent(id)}/agent-retry`, { run_id, confirmed: true }, key); }
  experimentDraft(id: string, version: string, scenario_label: string, key: string) { return this.request<AgentResult>(`/projects/${encodeURIComponent(id)}/experiment-draft`, { scene_version_id: version, scenario_label }, key); }
}

export const api = new ApiClient();
export type { Envelope };
