package com.shomer.cli.commands

import com.shomer.sdk.ShomerResult

/**
 * `demo` — runs the curated golden set (resources/golden_inputs.jsonl) and prints
 * predicted vs. expected per row plus a pass count. The cheapest end-to-end proof
 * that the ShomerApi port + wire contract hold against a live server.
 *
 * Note: the golden set is parsed leniently (the curated rows contain no quotes/
 * escapes inside the text), keeping the CLI free of a JSON dependency.
 */
class DemoCommand : BaseCommand("demo", "Run the curated golden set against the server.") {

    private val textRegex = Regex("\"text\"\\s*:\\s*\"(.*?)\"")
    private val expectedRegex = Regex("\"expected\"\\s*:\\s*\"(.*?)\"")

    override fun run() = withClient { api ->
        val lines = javaClass.getResourceAsStream("/golden_inputs.jsonl")
            ?.bufferedReader()?.readLines()
            ?.filter { it.isNotBlank() }
            ?: run {
                echo("✗ golden_inputs.jsonl not found on classpath", err = true)
                throw com.github.ajalt.clikt.core.ProgramResult(1)
            }

        var passed = 0
        var graded = 0
        echo("Running ${lines.size} golden rows against $server\n")
        for ((i, line) in lines.withIndex()) {
            val text = textRegex.find(line)?.groupValues?.get(1) ?: continue
            val expected = expectedRegex.find(line)?.groupValues?.get(1)
            when (val result = api.classify(text)) {
                is ShomerResult.Success -> {
                    val got = result.value.category
                    val mark = when {
                        expected == null -> "•"
                        got == expected -> { passed++; graded++; "✓" }
                        else -> { graded++; "✗" }
                    }
                    echo("$mark [${i + 1}] got=$got" + (expected?.let { " expected=$it" } ?: "") + "  \"${text.take(40)}\"")
                }
                is ShomerResult.Failure -> echo("! [${i + 1}] error=${result.error.message}")
            }
        }
        if (graded > 0) echo("\n$passed/$graded matched expected label")
    }
}
