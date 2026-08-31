"""Hoja de estilo QSS — paleta inspirada en Catppuccin Mocha."""

import sys as _sys

# Fuente de UI segun plataforma: en macOS 'Segoe UI'/'Inter' no existen y Qt
# gasta ~300 ms poblando alias + avisa "missing font family". Se usa una fuente
# nativa de cada SO para evitarlo (Windows sigue con Segoe UI).
_UI_FONT = ("'Helvetica Neue', 'Arial', sans-serif" if _sys.platform == "darwin"
            else "'Segoe UI', 'Inter', sans-serif")

DARK_QSS = """
* {
    font-family: __UI_FONT__;
    font-size: 10pt;
    color: #cdd6f4;
}

QMainWindow, QWidget {
    background-color: #1e1e2e;
}

QScrollArea, QScrollArea > QWidget > QWidget {
    background-color: #1e1e2e;
    border: none;
}

/* Tooltips (texto al pasar el cursor): ventana blanca, texto negro.
   Sin esto heredan el color claro de la regla `*` sobre el fondo amarillo
   por defecto de Qt -> texto ilegible. */
QToolTip {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 9pt;
}

QLabel#TitleLabel {
    font-size: 16pt;
    font-weight: 700;
    color: #cba6f7;
    padding: 4px 0 12px 0;
}

QLabel#SubtitleLabel {
    color: #a6adc8;
    font-size: 9pt;
    padding-bottom: 8px;
}

QLabel#StatusLabel {
    color: #94e2d5;
    font-weight: 600;
    padding: 6px 10px;
    background: #181825;
    border: 1px solid #313244;
    border-radius: 6px;
}

QGroupBox {
    border: 1px solid #45475a;
    border-radius: 10px;
    margin-top: 14px;
    margin-right: 4px;
    margin-left: 2px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
    color: #89b4fa;
    background-color: #181825;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    background-color: #1e1e2e;
}

QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #313244;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #89b4fa, stop:1 #cba6f7);
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #f5e0dc;
    border: 2px solid #cba6f7;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background: #cba6f7;
    border: 2px solid #f5e0dc;
}

QSpinBox, QDoubleSpinBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 6px;
    selection-background-color: #585b70;
}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #45475a;
    border: none;
    width: 16px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: #585b70;
}

QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #45475a;
    border: 1px solid #89b4fa;
    color: #f5e0dc;
}

QPushButton:pressed {
    background-color: #585b70;
}

QPushButton#PrimaryButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: 1px solid #cba6f7;
}

QPushButton#PrimaryButton:hover {
    background-color: #cba6f7;
    color: #1e1e2e;
}

QScrollBar:vertical {
    background: #181825;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #89b4fa;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QWidget#FooterBar {
    background-color: #181825;
    border-top: 1px solid #313244;
}

QPushButton:checked {
    background-color: #cba6f7;
    color: #1e1e2e;
    border: 1px solid #f5e0dc;
}

QPushButton:checked:hover {
    background-color: #f5c2e7;
}

QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 5px 10px;
    min-width: 90px;
    font-weight: 600;
}
QComboBox:hover {
    border-color: #89b4fa;
    color: #f5e0dc;
}
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #45475a;
    outline: 0;
}

/* Popups modales (QMessageBox / QInputDialog): fondo blanco / letra negra,
   coherente con el tema claro de los diálogos. Son ventanas top-level (NO
   hijas del diálogo que las lanza), así que NO heredan LIGHT_QSS; se estilan
   acá, en la hoja global, para que salgan claros desde cualquier parte de la
   app sin tocar los ~100 call-sites estáticos. Paleta = style.LIGHT (Latte).
   La especificidad `QMessageBox QLabel` le gana a la regla `*`. */
QMessageBox, QInputDialog { background-color: #ffffff; }
QMessageBox QLabel, QInputDialog QLabel { color: #11111b; background: transparent; }
QInputDialog QLineEdit, QInputDialog QSpinBox, QInputDialog QDoubleSpinBox,
QInputDialog QComboBox {
    background-color: #ffffff; color: #11111b;
    border: 1px solid #bcc0cc; border-radius: 6px; padding: 4px 6px;
    selection-background-color: #1e66f5; selection-color: #ffffff;
}
QInputDialog QComboBox QAbstractItemView {
    background-color: #ffffff; color: #11111b;
    selection-background-color: #dce0e8; selection-color: #11111b;
    border: 1px solid #bcc0cc;
}
QMessageBox QPushButton, QInputDialog QPushButton {
    background-color: #eff1f5; color: #11111b;
    border: 1px solid #bcc0cc; border-radius: 8px;
    padding: 6px 16px; font-weight: 600; min-width: 72px;
}
QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
    background-color: #dce0e8; border-color: #1e66f5; color: #1e66f5;
}
QMessageBox QPushButton:pressed, QInputDialog QPushButton:pressed { background-color: #bcc0cc; }
QMessageBox QPushButton:default, QInputDialog QPushButton:default {
    background-color: #1e66f5; color: #ffffff; border-color: #1e66f5;
}
QMessageBox QPushButton:default:hover, QInputDialog QPushButton:default:hover {
    background-color: #8839ef; border-color: #8839ef;
}
"""

DARK_QSS = DARK_QSS.replace("__UI_FONT__", _UI_FONT)


# ---------------------------------------------------------------------------
# Tema CLARO para diálogos (fondo blanco / letra negra).
#
# La ventana principal se queda con DARK_QSS (Catppuccin Mocha). Los diálogos
# se invierten a fondo blanco porque sus gráficos matplotlib ya son claros
# (figura #f0f0f0 / ejes #ffffff) y el marco oscuro rompía la coherencia.
#
# Paleta = Catppuccin **Latte** (la variante clara oficial de Mocha; mismo
# sistema de color, mismos hues, contraste calibrado sobre fondo claro).
# Cada acento del tema oscuro tiene su contraparte directa en Latte, así el
# mapeo oscuro->claro de los textos de color inline es principiado.
# Ref.: https://github.com/catppuccin/catppuccin (paletas Mocha/Latte).
#
# LIGHT = mapeo semantico usado tanto por el QSS como por los labels inline
# (una sola fuente de verdad para el reajuste de textos de color).
LIGHT = {
    "bg":      "#ffffff",  # fondo del diálogo (blanco puro, pedido del usuario)
    "inset":   "#eff1f5",  # Latte base: paneles/insets/groupbox
    "text":    "#11111b",  # casi negro: cuerpo de texto (Mocha crust invertido)
    "subtext": "#6c6f85",  # Latte subtext0: notas/hints grises
    "border":  "#bcc0cc",  # Latte surface1: bordes
    "blue":    "#1e66f5",  # Latte blue: títulos / botón primario / acento
    "mauve":   "#8839ef",  # Latte mauve: acento secundario
    "teal":    "#179299",  # Latte teal: estado/OK (contraparte de #94e2d5)
    "green":   "#40a02b",  # Latte green
    "amber":   "#b45309",  # ámbar oscurecido: advertencias legibles sobre blanco
    "red":     "#d20f39",  # Latte red: errores
    "sel":     "#dce0e8",  # Latte crust: selección/hover suave
}

_LIGHT_QSS = """
* {
    font-family: __UI_FONT__;
    font-size: 10pt;
    color: __text__;
}

QDialog, QWidget {
    background-color: __bg__;
}

QScrollArea, QScrollArea > QWidget > QWidget {
    background-color: __bg__;
    border: none;
}

QToolTip {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid __border__;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 9pt;
}

QLabel { background: transparent; }

QLabel#TitleLabel {
    font-size: 16pt;
    font-weight: 700;
    color: __blue__;
    padding: 4px 0 12px 0;
}

QLabel#SubtitleLabel {
    color: __subtext__;
    font-size: 9pt;
    padding-bottom: 8px;
}

QGroupBox {
    border: 1px solid __border__;
    border-radius: 10px;
    margin-top: 14px;
    margin-right: 4px;
    margin-left: 2px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
    color: __blue__;
    background-color: __inset__;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    background-color: __bg__;
}

QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: __border__;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 __blue__, stop:1 __mauve__);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid __blue__;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover { border: 2px solid __mauve__; }

QSpinBox, QDoubleSpinBox, QLineEdit {
    background-color: #ffffff;
    color: __text__;
    border: 1px solid __border__;
    border-radius: 6px;
    padding: 4px 6px;
    selection-background-color: __blue__;
    selection-color: #ffffff;
}
QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
    border: 1px solid __blue__;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: __inset__;
    border: none;
    width: 16px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: __sel__;
}

QPlainTextEdit, QTextEdit {
    background-color: #ffffff;
    color: __text__;
    border: 1px solid __border__;
    border-radius: 6px;
    selection-background-color: __blue__;
    selection-color: #ffffff;
}

QPushButton {
    background-color: __inset__;
    color: __text__;
    border: 1px solid __border__;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: __sel__;
    border: 1px solid __blue__;
    color: __blue__;
}
QPushButton:pressed { background-color: __border__; }
QPushButton:disabled { color: __subtext__; border-color: __sel__; }

QPushButton#PrimaryButton {
    background-color: __blue__;
    color: #ffffff;
    border: 1px solid __blue__;
}
QPushButton#PrimaryButton:hover {
    background-color: __mauve__;
    color: #ffffff;
    border: 1px solid __mauve__;
}

QPushButton:checked {
    background-color: __blue__;
    color: #ffffff;
    border: 1px solid __blue__;
}
QPushButton:checked:hover { background-color: __mauve__; }

QComboBox {
    background-color: #ffffff;
    color: __text__;
    border: 1px solid __border__;
    border-radius: 6px;
    padding: 5px 10px;
    min-width: 90px;
    font-weight: 600;
}
QComboBox:hover { border-color: __blue__; color: __blue__; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: __text__;
    selection-background-color: __sel__;
    selection-color: __text__;
    border: 1px solid __border__;
    outline: 0;
}

QCheckBox, QRadioButton { color: __text__; background: transparent; spacing: 6px; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px; height: 16px;
    border: 1px solid __border__;
    background: #ffffff;
}
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: __blue__;
    border: 1px solid __blue__;
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border: 1px solid __blue__; }

QListWidget, QTreeWidget, QTableWidget {
    background-color: #ffffff;
    color: __text__;
    border: 1px solid __border__;
    border-radius: 6px;
    outline: 0;
    selection-background-color: __sel__;
    selection-color: __text__;
    gridline-color: __border__;
    alternate-background-color: __inset__;
}
QListWidget::item:selected, QTreeWidget::item:selected,
QTableWidget::item:selected { background: __sel__; color: __text__; }
QListWidget::item:hover, QTreeWidget::item:hover { background: __inset__; }

QHeaderView::section {
    background-color: __inset__;
    color: __text__;
    border: none;
    border-right: 1px solid __border__;
    border-bottom: 1px solid __border__;
    padding: 4px 6px;
    font-weight: 600;
}
QTableCornerButton::section { background-color: __inset__; border: none; }

QTabWidget::pane { border: 1px solid __border__; border-radius: 6px; top: -1px; }
QTabBar::tab {
    background: __inset__;
    color: __subtext__;
    border: 1px solid __border__;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 12px;
}
QTabBar::tab:selected { background: #ffffff; color: __blue__; font-weight: 600; }

QScrollBar:vertical {
    background: __inset__;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: __border__;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: __blue__; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: __inset__;
    height: 10px;
    margin: 0;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: __border__;
    border-radius: 5px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: __blue__; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* Alias de object-names usados por shape_dialog / section_dialog. */
QLabel#DialogTitle { color: __blue__; font-size: 14pt; font-weight: 700; }
QLabel#DialogInfo { color: __subtext__; font-size: 9pt; padding-bottom: 2px; }
QLabel#DialogStatus { color: __teal__; font-weight: 600; font-size: 8pt; }
QLabel#DialogCoord { color: __amber__; font-weight: 600; }
QPushButton#DialogPrimary {
    background-color: __blue__; color: #ffffff; border: 1px solid __blue__;
}
QPushButton#DialogPrimary:hover { background-color: __mauve__; border-color: __mauve__; }
QPushButton#DialogPrimary:disabled { background-color: __sel__; color: __subtext__; border-color: __border__; }
"""

# Sustitución de tokens: fuente + paleta LIGHT.
LIGHT_QSS = _LIGHT_QSS.replace("__UI_FONT__", _UI_FONT)
for _k, _v in LIGHT.items():
    LIGHT_QSS = LIGHT_QSS.replace("__%s__" % _k, _v)


def apply_dialog_theme(widget):
    """Aplica el tema CLARO (fondo blanco / letra negra) a un diálogo.

    Se llama al final del __init__ de cada QDialog. El stylesheet se setea
    sobre la instancia del diálogo, así cascada a todos sus hijos y anula el
    DARK_QSS global solo para ese subárbol (la ventana principal queda oscura).
    """
    widget.setStyleSheet(LIGHT_QSS)
