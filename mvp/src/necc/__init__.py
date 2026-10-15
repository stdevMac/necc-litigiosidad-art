"""NECC · Automatización de la extracción de indicadores de litigiosidad de ART."""


def main() -> None:
    from .cli import main as _main

    _main()
