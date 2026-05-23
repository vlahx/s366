"""Constante și validare pentru prompturile companiei (rol + audiență)."""

PROMPT_ROLES = ("comportament", "reguli", "rag_manuale", "general")
AUDIENCES = ("toti", "studenti", "profesori", "intern")

PROMPT_ROLE_LABELS = {
    "comportament": "Comportament asistent",
    "reguli": "Reguli, format și politici",
    "rag_manuale": "Manuale RAG",
    "general": "General",
}

AUDIENCE_LABELS = {
    "toti": "Toți utilizatorii",
    "studenti": "Studenți",
    "profesori": "Profesori / admin curs",
    "intern": "Intern (staff firmă)",
}

# Ordine la asamblarea system prompt
ROLE_SORT_ORDER = {r: i for i, r in enumerate(PROMPT_ROLES)}

# Migrare din coloana veche `type`
_LEGACY_TYPE_MAP = {
    "General": ("general", "toti"),
    "Intern": ("general", "intern"),
    "Extern": ("general", "toti"),
    "HR": ("reguli", "intern"),
    "SALES": ("general", "toti"),
    "TECH": ("comportament", "toti"),
}


def normalize_prompt_role(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v == "format_raspuns":
        return "reguli"
    return v if v in PROMPT_ROLES else "general"


def normalize_audience(value: str | None) -> str:
    v = (value or "").strip().lower()
    return v if v in AUDIENCES else "toti"


def audiences_for_user(user_role: str | None) -> frozenset[str]:
    """Ce valori `audience` din DB se aplică acestui utilizator."""
    role = (user_role or "").strip().lower()
    if role in ("company_admin", "superadmin"):
        return frozenset({"toti", "profesori", "intern", "studenti"})
    if role == "pending_admin":
        return frozenset({"toti", "intern"})
    # users, user, guest, external — studenți / public
    return frozenset({"toti", "studenti"})
