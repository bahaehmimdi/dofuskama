"""Scraping du prix de référence sur leskamas.com pour la commande /apply.

Chaque appel revisite la page en direct (pas de cache) : le prix affiché est
toujours celui du moment. La page publie un tableau à sections ("Dofus Kamas",
"Dofus Touch Kamas", ...), une ligne d'en-tête à 7 colonnes suivie de lignes
serveur ; les lignes de section n'ont qu'une seule cellule.
"""

import asyncio
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

REFERENCE_URL = "https://www.leskamas.com/vendre-des-kamas.html"
DEFAULT_SECTION = "Dofus Kamas"
DISCOUNT = 0.06  # on affiche -6% du prix de référence

# L'autocomplétion Discord doit répondre en ~3s et est appelée à chaque
# frappe : on ne revisite PAS le site à chaque lettre tapée, seulement la
# liste des noms de serveur, mise en cache brièvement. La commande /apply
# elle-même revisite toujours le site en direct (voir fetch_reference_prices).
_AUTOCOMPLETE_CACHE_TTL = 120
_autocomplete_cache: dict[str, tuple[float, list[str]]] = {}

_NUMBER_RE = re.compile(r"[\d]+(?:[.,]\d+)?")


class ReferencePriceError(Exception):
    pass


def _parse_dhs_per_million(cell_text: str) -> Optional[float]:
    match = _NUMBER_RE.search(cell_text)
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def _fetch_sync() -> dict[str, dict[str, float]]:
    try:
        resp = requests.get(
            REFERENCE_URL,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (dofuskama-bot price reference)"},
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ReferencePriceError(f"Impossible de contacter leskamas.com : {exc}") from exc

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if table is None:
        raise ReferencePriceError("Structure de la page leskamas.com inattendue (table introuvable).")

    sections: dict[str, dict[str, float]] = {}
    current_section = None

    for row in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]

        if not cells or cells[0] == "Server":
            continue

        if len(cells) == 1:
            current_section = cells[0]
            sections[current_section] = {}
            continue

        if current_section is None or len(cells) < 5:
            continue

        server_name = cells[0]
        price = _parse_dhs_per_million(cells[4])  # colonne "Maroc(Dhs)"
        if price is not None:
            sections[current_section][server_name] = price

    if not sections:
        raise ReferencePriceError("Aucune donnée de prix trouvée sur leskamas.com.")

    return sections


async def fetch_reference_prices() -> dict[str, dict[str, float]]:
    """{section: {server: prix_dhs_par_million_kamas}}. Revisite le site à chaque appel."""
    return await asyncio.to_thread(_fetch_sync)


async def fetch_server_price(server: str, section: str = DEFAULT_SECTION) -> float:
    sections = await fetch_reference_prices()
    servers = sections.get(section)
    if not servers:
        raise ReferencePriceError(f"Section « {section} » introuvable sur leskamas.com.")

    match = next((v for k, v in servers.items() if k.lower() == server.lower()), None)
    if match is None:
        raise ReferencePriceError(
            f"Serveur « {server} » introuvable dans la section « {section} »."
        )
    return match


def apply_discount(reference_price_per_million: float) -> float:
    return reference_price_per_million * (1 - DISCOUNT)


def format_table(servers: dict) -> str:
    lines = ["Serveur          Réf(Dhs/M)  -6%(Dhs/M)", "-" * 40]
    for name, ref in sorted(servers.items()):
        applied = apply_discount(ref)
        lines.append(f"{name:<16} {ref:>10.3f}  {applied:>10.3f}")
    return "```\n" + "\n".join(lines) + "\n```"


async def list_server_names(section: str = DEFAULT_SECTION) -> list[str]:
    cached = _autocomplete_cache.get(section)
    if cached and (time.monotonic() - cached[0]) < _AUTOCOMPLETE_CACHE_TTL:
        return cached[1]

    try:
        sections = await fetch_reference_prices()
    except ReferencePriceError:
        return cached[1] if cached else []

    names = list(sections.get(section, {}).keys())
    _autocomplete_cache[section] = (time.monotonic(), names)
    return names
