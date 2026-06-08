package com.shomer.cli.commands

import com.github.ajalt.clikt.parameters.arguments.argument
import java.io.File

/** `classify-image <path>` — POST /classify-image (multipart). */
class ClassifyImageCommand : BaseCommand("classify-image", "OCR + classify a chat screenshot.") {

    private val path: String by argument(name = "path", help = "Path to a JPEG/PNG image file")

    override fun run() = withClient { api ->
        val file = File(path)
        if (!file.exists()) {
            echo("✗ File not found: $path", err = true)
            throw com.github.ajalt.clikt.core.ProgramResult(1)
        }
        val mime = if (file.extension.lowercase() == "png") "image/png" else "image/jpeg"
        render(api.classify(file.readBytes(), mime)) { r ->
            val flag = if (r.isOffensive) "⚠ OFFENSIVE" else "✓ clean"
            echo("$flag  category=${r.category}  confidence=${"%.3f".format(r.confidence)}  backend=${r.backend}  ${r.latencyMs}ms")
            if (verbose) echo("  extracted_text: ${r.extractedText}")
        }
    }
}
