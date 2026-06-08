package com.shomer.cli.commands

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.parameters.options.default
import com.github.ajalt.clikt.parameters.options.flag
import com.github.ajalt.clikt.parameters.options.option
import com.shomer.sdk.ShomerApi
import com.shomer.sdk.ShomerClient
import com.shomer.sdk.ShomerError
import com.shomer.sdk.ShomerResult
import com.shomer.sdk.SdkConfig
import kotlinx.coroutines.runBlocking

/**
 * Shared options + plumbing for every CLI subcommand: builds the [ShomerApi] from
 * `--server`/`--api-key`, runs a suspending block, and pretty-prints [ShomerError]s
 * with a non-zero exit on failure.
 */
abstract class BaseCommand(name: String, help: String) : CliktCommand(name = name, help = help) {

    protected val server: String by option("--server", help = "FastAPI base URL").default("http://localhost:8000/")
    protected val apiKey: String by option("--api-key", help = "Bearer token (Phase-9 auth; optional)").default("")
    protected val verbose: Boolean by option("--verbose", "-v", help = "Print full result details").flag()

    private fun client(): ShomerApi = ShomerClient.create(
        SdkConfig(baseUrl = server, apiKey = apiKey.ifBlank { null }),
    )

    /** Runs [block] with a fresh client, closing it afterwards. */
    protected fun withClient(block: suspend (ShomerApi) -> Unit) {
        val api = client()
        try {
            runBlocking { block(api) }
        } finally {
            api.close()
        }
    }

    /** Renders a [ShomerResult]: prints the success line(s) or the error, sets exit code. */
    protected fun <T> render(result: ShomerResult<T>, onSuccess: (T) -> Unit) {
        when (result) {
            is ShomerResult.Success -> onSuccess(result.value)
            is ShomerResult.Failure -> {
                echo("✗ ${describe(result.error)}", err = true)
                throw com.github.ajalt.clikt.core.ProgramResult(1)
            }
        }
    }

    private fun describe(e: ShomerError): String = when (e) {
        is ShomerError.NetworkError -> "Network error: ${e.message} (is the server running at $server ?)"
        is ShomerError.ServerError -> "Server error ${e.httpStatus}: ${e.message}"
        is ShomerError.RateLimitError -> "Rate limited" + (e.retryAfterSeconds?.let { " — retry after ${it}s" } ?: "")
        is ShomerError.ValidationError -> "Validation error: ${e.detail}"
        is ShomerError.TimeoutError -> "Timed out after ${e.timeoutMs}ms"
        is ShomerError.ParseError -> "Parse error: ${e.message}"
    }
}
