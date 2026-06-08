// Root build for the Shomer.AI SDK composite.
// Plugins are declared here (apply false) and applied per-module.

plugins {
    kotlin("jvm") version "2.2.0" apply false
}

allprojects {
    group = "com.shomer"
    version = "1.0.0"

    repositories {
        mavenCentral()
    }
}
