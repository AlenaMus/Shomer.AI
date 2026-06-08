package com.shomer.cli.commands

/** `info` — GET /model/info. */
class InfoCommand : BaseCommand("info", "Print model metadata (id, base, labels).") {

    override fun run() = withClient { api ->
        render(api.modelInfo()) { m ->
            echo("model=${m.model}")
            echo("base=${m.base ?: "(none)"}")
            echo("labels=${m.labels.joinToString(", ")}")
        }
    }
}
