package com.shomer.cli.commands

import com.github.ajalt.clikt.parameters.arguments.argument

/** `classify <hebrew text>` — POST /classify. */
class ClassifyCommand : BaseCommand("classify", "Classify a Hebrew text string.") {

    private val text: String by argument(name = "text", help = "Hebrew text to classify")

    override fun run() = withClient { api ->
        render(api.classify(text)) { r ->
            val flag = if (r.isOffensive) "⚠ OFFENSIVE" else "✓ clean"
            echo("$flag  category=${r.category}  confidence=${"%.3f".format(r.confidence)}  model=${r.model}  ${r.latencyMs}ms")
            if (verbose) {
                echo("  reviewFlag=${r.reviewFlag}  contextUsed=${r.contextUsed}")
                r.reasoningTrace?.let { echo("  reasoning: $it") }
            }
        }
    }
}
