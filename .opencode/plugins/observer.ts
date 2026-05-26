import type { Plugin } from "@opencode-ai/plugin"

export const ObserverPlugin: Plugin = async ({ project, directory }) => {
  const log = (event: string, data?: unknown) => {
    const time = new Date().toISOString().slice(11, 23)
    console.log(`\n[HOOK] ${time} ▶ ${event}`)
    if (data) console.log("       ", JSON.stringify(data).slice(0, 120))
  }

  log("plugin.init", { project: directory })

  return {
    // ✅ 正确事件名
    "session.created": async (session: any) => {
      log("session.created", { id: session?.id })
    },

    "message.updated": async (message: any) => {
      log("message.updated", {
        role: message?.role,
        preview: String(message?.parts?.[0]?.text ?? "").slice(0, 50)
      })
    },

    "tool.execute.before": async (input: any, output: any) => {
      log("tool.execute.before", {
        tool: input?.tool,
        args: input?.args
      })
    },

    "tool.execute.after": async (input: any, output: any) => {
      log("tool.execute.after", {
        tool: input?.tool,
        ok: !output?.error
      })
    },

    "file.edited": async (file: any) => {
      log("file.edited", { path: file?.path })
    },

    "session.idle": async () => {
      log("session.idle", { msg: "AI 完成本轮回复" })
    }
  }
}