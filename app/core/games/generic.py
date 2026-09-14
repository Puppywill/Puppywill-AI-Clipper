"""
generic.py
----------
Perfil por defecto del modo Gaming cuando el juego es "Auto Detect" o
"Other": no asume el HUD de ningún título en particular. Solo incluye
una región de kill feed (misma posición por defecto que ya usa el modo
General en visual_analysis.KILL_FEED_ROI_FRAC - la franja superior-
derecha es la convención más común en shooters), sin barra de ultimate
ni banner de ronda (varían demasiado entre juegos para adivinar sin
datos). El modo Gaming con este perfil sigue funcionando igual de bien
por audio + brillo/optical flow, que no dependen de conocer el juego.
"""
from __future__ import annotations

from . import GameProfile

GENERIC_PROFILE = GameProfile(
    key="generic",
    name="Genérico",
    hud_regions={
        "kill_feed": (0.55, 0.34, 1.0, 0.46),
    },
)
