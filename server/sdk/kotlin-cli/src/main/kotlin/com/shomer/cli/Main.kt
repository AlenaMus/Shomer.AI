package com.shomer.cli

import com.github.ajalt.clikt.core.CliktCommand
import com.github.ajalt.clikt.core.subcommands
import com.shomer.cli.commands.ClassifyCommand
import com.shomer.cli.commands.ClassifyImageCommand
import com.shomer.cli.commands.DemoCommand
import com.shomer.cli.commands.HealthCommand
import com.shomer.cli.commands.InfoCommand

/**
 * Root command. Connection options (`--server`, `--api-key`, `--verbose`) live on
 * each subcommand (see [com.shomer.cli.commands.BaseCommand]) so the documented
 * `demo --server …` / `classify-image x.png --verbose` forms work.
 *
 * ```
 * java -jar shomer-cli.jar classify "תפסיק להיות כזה לוזר"
 * java -jar shomer-cli.jar classify-image screenshot.png --verbose
 * java -jar shomer-cli.jar health --server http://localhost:8000
 * java -jar shomer-cli.jar info
 * java -jar shomer-cli.jar demo
 * ```
 */
class ShomerCli : CliktCommand(
    name = "shomer-cli",
    help = "Terminal client for the Shomer.AI server — wraps the :sdk ShomerApi.",
) {
    override fun run() = Unit // dispatches to subcommands
}

fun main(args: Array<String>) {
    ShomerCli()
        .subcommands(
            ClassifyCommand(),
            ClassifyImageCommand(),
            HealthCommand(),
            InfoCommand(),
            DemoCommand(),
        )
        .main(args)
}
