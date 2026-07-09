"""
timed_button.py
===============

Helper para mostrar una leyenda "Ultimo: X.XX s" persistente debajo de un
QPushButton cada vez que se hace click. Lo usamos en los botones de calculo
pesado (Calcular modos FEM, Predecir, Importar CAD, Aplicar candidato) para
que el usuario sepa cuanto tardo el ultimo calculo sin tener que abrir un log.

Uso:
    btn = QPushButton("Calcular modos (FEM)")
    layout.addWidget(btn)
    timer = TimedButton(btn, parent_layout=layout)
    # En el handler del click:
    timer.start()
    ... heavy work ...
    timer.stop()    # actualiza la leyenda con el elapsed
"""

from __future__ import annotations
import time
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QBoxLayout, QFormLayout


class TimedButton:
    """Wrapper que asocia un QLabel persistente debajo de un boton.

    El label muestra "Ultimo: X.XX s" cuando hay una medicion. Antes del
    primer click esta vacio (no ocupa espacio visual notable). Si la
    operacion falla, se puede llamar fail() para mostrar "(fallo)".
    """

    LABEL_STYLE = "color: #6c7086; font-size: 8pt; padding: 0 4px;"
    LABEL_STYLE_FRESH = "color: #94e2d5; font-size: 8pt; padding: 0 4px;"
    LABEL_STYLE_ERROR = "color: #f38ba8; font-size: 8pt; padding: 0 4px;"

    def __init__(self, button, parent_layout: QBoxLayout,
                 prefix: str = "Último:"):
        self.button = button
        self.prefix = prefix
        self.label = QLabel("")
        self.label.setStyleSheet(self.LABEL_STYLE)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumHeight(14)
        # Insertar el label inmediatamente despues del boton en el layout.
        idx = parent_layout.indexOf(button)
        if idx >= 0:
            parent_layout.insertWidget(idx + 1, self.label)
        else:
            parent_layout.addWidget(self.label)
        self._t_start: Optional[float] = None

    def start(self):
        self._t_start = time.time()
        # Mientras corre, dejamos el ultimo valor visible para que el usuario
        # no vea un flash vacio. Si nunca corrio, sigue vacio.

    def stop(self, label: Optional[str] = None) -> float:
        """Detiene el cronometro y actualiza la leyenda.

        Si `label` esta dado, lo agrega despues del tiempo (ej: 'Ultimo: 2.34 s · cobertura completa').
        Devuelve el elapsed en segundos.
        """
        if self._t_start is None:
            return 0.0
        elapsed = time.time() - self._t_start
        self._t_start = None
        text = f"{self.prefix} {elapsed:.2f} s"
        if label:
            text += f"  ·  {label}"
        self.label.setText(text)
        self.label.setStyleSheet(self.LABEL_STYLE_FRESH)
        # Fade a color normal despues de 1.5 s (visual: highlight reciente)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(
            1500, lambda: self.label.setStyleSheet(self.LABEL_STYLE)
        )
        return elapsed

    def fail(self, msg: str = "falló"):
        """Marca la ultima ejecucion como fallida."""
        self._t_start = None
        self.label.setText(f"({msg})")
        self.label.setStyleSheet(self.LABEL_STYLE_ERROR)


def add_timed_label_to_form(form_layout: QFormLayout, button) -> 'TimedButton':
    """Caso especial: el boton vive en una row sin label de un QFormLayout.
    Inserta el QLabel como una nueva row sin etiqueta inmediatamente despues.
    """
    timer = _TimedButtonForm(button, form_layout)
    return timer


class _TimedButtonForm(TimedButton):
    """Variante para QFormLayout: agrega el label como row span-2 abajo."""

    def __init__(self, button, form_layout: QFormLayout,
                 prefix: str = "Último:"):
        # Saltamos el __init__ del padre porque ese asume QBoxLayout.
        self.button = button
        self.prefix = prefix
        self.label = QLabel("")
        self.label.setStyleSheet(self.LABEL_STYLE)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumHeight(14)
        # Buscar la row del boton para insertar despues. QFormLayout no tiene
        # insertRow despues de un widget concreto, asi que addRow al final
        # sirve mientras el boton este al final del FormLayout.
        form_layout.addRow(self.label)
        self._t_start = None
