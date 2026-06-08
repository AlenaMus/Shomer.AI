// :sdk-cli — clikt terminal runner that wraps the same :sdk ShomerApi
// (design.md §3.5). Proves the port works without Android; used for smoke
// tests and the architecture demo. Not part of the published :sdk artifact.

plugins {
    kotlin("jvm")
    application
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(project(":sdk"))
    implementation("com.github.ajalt.clikt:clikt:4.4.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")
    // A concrete SLF4J binding so the SDK's logging surfaces in the terminal.
    runtimeOnly("org.slf4j:slf4j-simple:2.0.9")
}

application {
    mainClass.set("com.shomer.cli.MainKt")
}

// Self-contained runnable jar: `./gradlew :sdk-cli:fatJar`
tasks.register<Jar>("fatJar") {
    group = "build"
    description = "Builds shomer-cli.jar with all dependencies bundled."
    archiveBaseName.set("shomer-cli")
    archiveClassifier.set("")
    archiveVersion.set("")
    manifest { attributes["Main-Class"] = "com.shomer.cli.MainKt" }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)
    from({
        configurations.runtimeClasspath.get()
            .filter { it.name.endsWith("jar") }
            .map { zipTree(it) }
    })
}
