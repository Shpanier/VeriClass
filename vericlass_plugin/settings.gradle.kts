rootProject.name = "vericlass-plugin"

// Two thin product modules that share one source tree (../core), each built
// against its own JetBrains IDE. See core/ for the shared Kotlin sources.
include(":clion", ":pycharm")
