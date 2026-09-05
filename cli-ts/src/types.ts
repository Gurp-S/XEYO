export type ToolStatus = "running" | "completed" | "error";

export type TodoStatus = "pending" | "in_progress" | "completed";

/** TodoWrite 清单中的单行（SSE tool_result.todos 归一化后）。 */
export type TodoRow = {
  content: string;
  status: TodoStatus;
};

/** usage 事件：本轮模型 token 用量（字段以 GUI core.ts 为准）。 */
export type UsageInfo = {
  promptTokens: number;
  completionTokens: number;
  cacheHitTokens?: number;
  cacheMissTokens?: number;
  cny?: number;
  contextLimit?: number;
};

export type TimelineItem =
  | {
      id: string;
      kind: "assistant";
      text: string;
      streaming?: boolean;
      /** 模型思考增量（reasoning_delta 累加）。 */
      reasoning?: string;
      /** 本轮 token 用量（usage 事件）。 */
      usage?: UsageInfo;
    }
  | {
      id: string;
      kind: "tool";
      name: string;
      summary: string;
      status: ToolStatus;
      result?: string;
      isError?: boolean;
      /** tool_progress 的实时进度文案。 */
      progress?: string;
      /** TodoWrite 清单（tool_result.todos 归一化）。 */
      todos?: TodoRow[];
    }
  | {
      id: string;
      kind: "user";
      text: string;
    }
  | {
      id: string;
      kind: "system";
      text: string;
    };

export type PermissionPrompt = {
  requestId: string;
  tool: string;
  prompt: string;
};

export type CliConfig = {
  baseUrl: string;
  apiKey: string;
  provider: string;
  model: string;
  cwd: string;
  sessionId: string;
  agentMode: string;
  permissionMode: string;
  demo: boolean;
  /** T_now 输出精简（/output off|lite|full|ultra） */
  outputCompact?: boolean;
  outputMode?: string;
  /** T_now 写代码精简（/code off|lite|full|ultra） */
  codeCompact?: boolean;
  codeMode?: string;
};
