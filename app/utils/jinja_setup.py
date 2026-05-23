"""Filtre Jinja comune (FastAPI nu include tojson ca Flask)."""
import json

from markupsafe import Markup


def tojson_filter(value) -> Markup:
    return Markup(json.dumps(value, ensure_ascii=False))


def register_common_jinja_filters(env) -> None:
    env.filters["tojson"] = tojson_filter
