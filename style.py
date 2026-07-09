"""Hoja de estilo QSS — paleta inspirada en Catppuccin Mocha."""

DARK_QSS = """
* {
    font-family: 'Segoe UI', 'Inter', sans-serif;
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
"""
