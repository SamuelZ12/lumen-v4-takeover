"""The ``serve`` program. Domain modules (config, traffic, ...) add its command groups."""

PROGRAMS = {
    "serve": (
        "Lumen model serving: configuration, traffic, replicas and model lifecycle.\n\n"
        "Config documents (serving/<model>.yaml, overrides/prod.yaml) live in the ops service;\n"
        "read and edit them only through `serve config`."
    )
}
