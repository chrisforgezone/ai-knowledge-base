import type { Plugin } from "@opencode-ai/plugin"

export const ObserverPlugin: Plugin = async ({ directory, $ }) => {
  const logFile = `${directory}/.opencode/observer.log`

  const log = async (event: string, data?: unknown) => {
    const time = new Date().toISOString().slice(11, 23)
    const dataStr = data ? `  ${JSON.stringify(data).slice(0, 120)}` : ""
    const line = `${time}  ▶ ${event}${dataStr}`
    await $`echo ${line} >> ${logFile}`.quiet()
  }

  await log("plugin.init", { directory })

  return {
    "session.created": async (session: any) => {
      await log("session.created", { id: session?.id })
    },

    "message.updated": async (message: any) => {
      await log("message.updated", {
        role: message?.role,
        preview: String(message?.parts?.[0]?.text ?? "").slice(0, 50)
      })
    },

    "tool.execute.before": async (input: any, output: any) => {
      await log("tool.execute.before", {
        tool: input?.tool,
        args: output?.args
      })
    },

    "tool.execute.after": async (input: any, output: any) => {
      await log("tool.execute.after", {
        tool: input?.tool,
        ok: !output?.error
      })
    },

    "file.edited": async (file: any) => {
      await log("file.edited", { path: file?.path })
    },

    "session.idle": async () => {
      await log("session.idle")
    },

    "session.deleted": async () => {
      await log("session.deleted")
    }
  }
}