package com.shomer.cli.commands

/** `health` — GET /health. */
class HealthCommand : BaseCommand("health", "Check server liveness + Ollama reachability.") {

    override fun run() = withClient { api ->
        render(api.health()) { h ->
            val mark = if (h.status == "ok") "✓" else "⚠"
            echo("$mark status=${h.status}  ollama_reachable=${h.ollamaReachable}  model=${h.model}")
        }
    }
}
