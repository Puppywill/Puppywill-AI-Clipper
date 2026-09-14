"""
games/
------
Perfiles de juego para el modo Gaming: qué regiones del HUD mirar y qué
palabras clave buscar por OCR, todo como fracciones (x0, y0, x1, y1) del
frame completo - nunca coordenadas absolutas, para que funcione sin
importar la resolución/encuadre de la grabación.

Un perfil es best-effort a propósito (igual que `KILL_FEED_ROI_FRAC` en
visual_analysis.py hoy): si el encuadre real del usuario no deja ver
una región, esa señal simplemente aporta ~0 y las demás (sobre todo
audio, que no depende del encuadre) siguen funcionando.

`get_profile("auto")` y `get_profile("other")` devuelven el mismo
`GENERIC_PROFILE` (sin URL de juego conocido - regiones conservadoras,
sin asumir HUD de ningún título en particular).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

RoiFrac = tuple[float, float, float, float]


@dataclass(frozen=True)
class GameProfile:
    key: str
    name: str  # nombre legible (español), solo para logs/debug - no se traduce ni se muestra tal cual en la UI
    # nombre de región -> fracción (x0, y0, x1, y1) del frame completo.
    # Regiones esperadas por gaming_events.py (todas opcionales, pueden
    # faltar): "kill_feed", "ultimate_bar", "round_banner".
    hud_regions: dict[str, RoiFrac] = field(default_factory=dict)
    # palabras clave (en minúsculas) que indican fin de ronda/victoria/derrota
    # en el banner central - vacío si no se conoce el idioma/fuente del juego
    transition_keywords: tuple[str, ...] = ()
    transition_text_roi: Optional[RoiFrac] = None


def get_profile(key: str) -> GameProfile:
    from . import generic, marvel_rivals

    profiles = {
        "auto": generic.GENERIC_PROFILE,
        "other": generic.GENERIC_PROFILE,
        "marvel_rivals": marvel_rivals.MARVEL_RIVALS_PROFILE,
    }
    return profiles.get(key, generic.GENERIC_PROFILE)
