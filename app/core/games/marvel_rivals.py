"""
marvel_rivals.py
-----------------
Perfil de Marvel Rivals para el modo Gaming. Regiones best-effort (ver
GameProfile): afinadas para el encuadre vertical típico de este proyecto
(cámara web arriba, área de juego abajo), NO coordenadas de píxeles del
juego en sí - si el encuadre real difiere, cada región simplemente
aporta ~0 sin romper nada más.

Pendiente de la Fase 3 del plan de Gaming Mode: ajustar `ultimate_bar` y
`round_banner` con clips cortos reales (ver plan `elegant-bouncing-
rain.md`) - por ahora son una primera aproximación razonable basada en
la convención de HUD de shooters tipo Overwatch (barra de habilidades/
ultimate abajo-centro, banner de fin de ronda en el centro de pantalla),
no medidas confirmadas sobre footage real de este perfil todavía.

`transition_keywords`/`transition_text_roi` son los mismos ya validados
en `kill_events.py` (movidos aquí para que vivan junto al resto del
perfil del juego); Tesseract no lee bien la fuente estilizada de este
juego (confirmado empíricamente), así que esto sigue siendo un refuerzo
de baja confianza, nunca un requisito.
"""
from __future__ import annotations

from . import GameProfile

MARVEL_RIVALS_PROFILE = GameProfile(
    key="marvel_rivals",
    name="Marvel Rivals",
    hud_regions={
        "kill_feed": (0.55, 0.34, 1.0, 0.46),
        "ultimate_bar": (0.35, 0.85, 0.65, 0.98),
        "round_banner": (0.0, 0.42, 1.0, 0.65),
    },
    transition_keywords=("complete", "defeat", "victory", "draw"),
    transition_text_roi=(0.0, 0.42, 1.0, 0.65),
)
