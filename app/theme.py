"""Dark theme tokens + global QSS. Same structure as Model Manager, cooler hue."""

from pathlib import Path

# Qt stylesheets want forward slashes even on Windows. CSS-border triangles do
# not render as ::down-arrow in this Qt build, so the carets are real SVGs.
ASSETS = Path(__file__).resolve().parent.joinpath("assets").as_posix()

C = {
    "bg":         "#131318",
    "surface":    "#1b1b22",
    "surface2":   "#23232c",
    "line":       "#34343f",
    "line_soft":  "#2b2b34",
    "ink":        "#f0eef5",
    "ink_dim":    "#bfbccb",
    "ink_mute":   "#8b8899",
    "accent":     "#8b7cf6",
    "accent_ink": "#14101f",
    "accent_dim": "#2a2340",
    "good":       "#79cf9a",
    "warn":       "#e0c56e",
    "bad":        "#e0736e",
}


def qss() -> str:
    return f"""
    * {{
        font-family: "Segoe UI", system-ui, sans-serif;
        color: {C['ink']};
        font-size: 12px;
    }}
    QMainWindow, QWidget#Root {{ background: {C['bg']}; }}

    /* ---- panes ---- */
    QWidget#Pane {{ background: {C['bg']}; }}
    QWidget#PaneHead {{ background: {C['bg']}; border-bottom: 1px solid {C['line_soft']}; }}
    QLabel#PaneTitle {{ font-size: 12px; font-weight: 500; letter-spacing: 0.3px; }}
    QLabel#PaneCount, QLabel#Muted {{ color: {C['ink_mute']}; font-size: 11px; }}
    QLabel#Hint {{ color: {C['ink_mute']}; font-size: 11px; }}

    QSplitter::handle {{ background: {C['line_soft']}; }}
    QSplitter::handle:horizontal {{ width: 5px; }}
    QSplitter::handle:horizontal:hover {{ background: {C['accent']}; }}

    /* ---- scrollbars ---- */
    QScrollArea {{ border: none; background: transparent; }}
    /* the viewport's inner widget defaults to the palette base (white) */
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {C['line']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {C['line_soft']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ---- buttons ---- */
    QPushButton {{
        background: transparent; color: {C['ink_dim']};
        border: 1px solid {C['line']}; border-radius: 7px;
        padding: 7px 13px; font-weight: 600; font-size: 12px;
    }}
    QPushButton:hover:enabled {{ color: {C['ink']}; background: {C['surface']}; }}
    QPushButton#Primary, QPushButton#AddBtn {{
        color: {C['accent_ink']}; background: {C['accent']}; border: none; font-weight: 700;
    }}
    QPushButton#Primary:hover:enabled, QPushButton#AddBtn:hover:enabled {{ background: #9c8ff8; }}

    /* split button — two widgets sitting flush, rounded only on the outside */
    QPushButton#AddBtnL {{
        color: {C['accent_ink']}; background: {C['accent']}; border: none; font-weight: 700;
        padding: 7px 12px; border-top-left-radius: 7px; border-bottom-left-radius: 7px;
        border-top-right-radius: 0; border-bottom-right-radius: 0;
    }}
    QToolButton#AddBtnR {{
        color: {C['accent_ink']}; background: {C['accent']}; border: none; font-weight: 700;
        padding: 7px 7px 7px 5px; font-size: 11px;
        border-top-right-radius: 7px; border-bottom-right-radius: 7px;
        border-top-left-radius: 0; border-bottom-left-radius: 0;
    }}
    QToolButton#AddBtnR::menu-indicator {{ image: none; width: 0; }}
    QPushButton#AddBtnL:hover, QToolButton#AddBtnR:hover {{ background: #9c8ff8; }}

    /* disabled must read as "locked", e.g. while generating */
    QPushButton:disabled {{ color: {C['line']}; border-color: {C['line_soft']}; background: transparent; }}
    QPushButton#Primary:disabled, QPushButton#AddBtn:disabled {{
        background: {C['accent_dim']}; color: {C['ink_mute']}; border: none;
    }}
    QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled, QSpinBox:disabled {{
        color: {C['ink_mute']}; border-color: {C['line_soft']}; background: {C['bg']};
    }}

    /* Qt gives tooltips the system palette unless told otherwise, which on
       Windows means black on white in the middle of a dark window */
    QToolTip {{
        background: {C['surface2']}; color: {C['ink_dim']};
        border: 1px solid {C['line']}; border-radius: 6px;
        padding: 5px 8px; font-size: 12px;
    }}

    /* the spoken line under a scene: readable, but never louder than the
       controls it sits beneath */
    QLabel#SceneLine {{ color: {C['ink_dim']}; font-size: 12px; }}

    /* the tick on a chosen picture — it sits on the image itself, so it needs
       its own dark disc or it vanishes into whatever is underneath */
    QCheckBox#TileMark::indicator {{
        width: 18px; height: 18px; border-radius: 9px;
        border: 2px solid rgba(12, 12, 18, 0.8); background: {C['accent']};
    }}
    QCheckBox#TileMark::indicator:checked {{ background: {C['accent']}; }}

    /* the x on a kept piece — solid, so it reads over any thumbnail */
    QPushButton#CardClose {{
        padding: 0; border: none; border-radius: 9px;
        background: rgba(12, 12, 18, 0.78); color: {C['ink']};
        font-weight: 700; font-size: 12px;
    }}
    QPushButton#CardClose:hover {{ background: {C['bad']}; color: #ffffff; }}

    /* the strip that says whether you are on voices or on footage */
    QWidget#ModeBar {{
        background: {C['surface']}; border-bottom: 1px solid {C['line_soft']};
    }}

    QPushButton#GBtn {{
        padding: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
        border: 1px solid {C['line']}; border-radius: 6px; color: {C['ink_mute']};
        font-weight: 700; font-size: 12px;
    }}
    QPushButton#GBtn:hover:enabled {{ color: {C['accent']}; border-color: {C['accent']}; }}
    QPushButton#GBtn:disabled {{ color: {C['line']}; border-color: {C['line_soft']}; }}

    /* ---- step tabs ---- */
    QPushButton#Step {{
        border: none; background: transparent; color: {C['ink_mute']};
        padding: 6px 14px; border-radius: 6px; font-weight: 600; font-size: 12px;
    }}
    QPushButton#Step:hover:enabled {{ color: {C['ink_dim']}; background: {C['surface']}; }}
    QPushButton#Step:checked {{ color: {C['ink']}; background: {C['surface2']}; }}
    QPushButton#Step:disabled {{ color: {C['line']}; }}

    /* ---- inputs ---- */
    QLineEdit {{
        background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 7px;
        padding: 7px 10px; color: {C['ink']}; font-size: 12px;
    }}
    QLineEdit:focus {{ border: 1px solid {C['accent']}; }}
    QTextEdit {{
        background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 7px;
        color: {C['ink']}; padding: 8px 10px; font-size: 12px;
    }}
    QTextEdit:focus {{ border: 1px solid {C['accent']}; }}
    QComboBox {{
        background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 6px;
        padding: 5px 9px; color: {C['ink']}; font-size: 12px; min-height: 20px;
    }}
    QComboBox:hover:enabled {{ border: 1px solid {C['line_soft']}; }}
    QComboBox:focus, QComboBox:on {{ border: 1px solid {C['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{
        image: url("{ASSETS}/caret-down.svg"); width: 9px; height: 6px; margin-right: 9px;
    }}
    QComboBox::down-arrow:on {{ image: url("{ASSETS}/caret-down-accent.svg"); }}
    QComboBox QAbstractItemView {{
        background: {C['surface2']}; color: {C['ink']}; border: 1px solid {C['line']};
        border-radius: 8px; padding: 4px; outline: none;
        selection-background-color: {C['accent_dim']};
    }}
    QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 3px 8px; border-radius: 5px; }}
    QSpinBox {{
        background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 6px;
        padding: 5px 8px; color: {C['ink']}; font-size: 12px; min-height: 20px;
    }}
    QSpinBox:focus {{ border: 1px solid {C['accent']}; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border; border: none; background: transparent; width: 16px;
    }}
    QSpinBox::up-button {{ subcontrol-position: top right; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QSpinBox::up-arrow {{ image: url("{ASSETS}/caret-up.svg"); width: 9px; height: 6px; }}
    QSpinBox::down-arrow {{ image: url("{ASSETS}/caret-down.svg"); width: 9px; height: 6px; }}
    QLabel#FieldLabel {{ color: {C['ink_mute']}; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; }}

    /* ---- project card ---- */
    QFrame#ProjCard {{ border: 1px solid transparent; border-radius: 10px; }}
    QFrame#ProjCard:hover {{ background: {C['surface']}; }}
    QFrame#ProjCard[selected="true"] {{ background: {C['surface']}; border: 1px solid {C['line']}; }}
    QLabel#ProjName {{ font-weight: 600; font-size: 13px; }}
    QLabel#ProjMeta {{ color: {C['ink_mute']}; font-size: 11px; }}
    QPushButton#CardDel {{
        padding: 0; border: none; border-radius: 10px; background: transparent;
        color: {C['ink_mute']}; font-size: 15px; font-weight: 700;
        min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
    }}
    QPushButton#CardDel:hover {{ background: {C['accent_dim']}; color: {C['accent']}; }}

    /* ---- scene card ---- */
    QFrame#SceneCard {{
        background: {C['surface']}; border: 1px solid {C['line_soft']}; border-radius: 10px;
    }}
    QFrame#SceneCard:hover {{ border: 1px solid {C['line']}; }}
    QLabel#SceneNum {{
        color: {C['accent']}; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
    }}
    QLabel#Chip {{
        color: {C['ink_dim']}; background: {C['surface2']}; border: 1px solid {C['line_soft']};
        border-radius: 9px; padding: 2px 9px; font-size: 10px; font-weight: 600;
    }}
    QLabel#ChipDraft, QLabel#ChipReady, QLabel#ChipRendered {{
        border-radius: 9px; padding: 3px 9px; font-size: 10px; font-weight: 700;
        letter-spacing: 0.5px;
    }}
    QLabel#ChipDraft {{ color: {C['ink_mute']}; background: {C['surface2']}; }}
    QLabel#ChipReady {{ color: {C['accent']}; background: {C['accent_dim']}; }}
    QLabel#ChipRendered {{ color: {C['good']}; background: #1d3328; }}

    /* ---- clip tiles / thumbnails ---- */
    QFrame#ClipTile {{
        background: {C['surface']}; border: 1px solid {C['line_soft']}; border-radius: 10px;
    }}
    QFrame#ClipTile:hover {{ background: {C['surface2']}; border: 1px solid {C['accent']}; }}
    QLabel#ClipThumb {{
        background: {C['bg']}; border: 1px solid {C['line_soft']}; border-radius: 6px;
        color: {C['ink_mute']}; font-size: 10px;
    }}

    QCheckBox {{ color: {C['ink_dim']}; font-size: 12px; spacing: 7px; }}
    QCheckBox:disabled {{ color: {C['line']}; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {C['line']};
        border-radius: 4px; background: {C['surface']};
    }}
    QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}
    QCheckBox::indicator:disabled {{ border-color: {C['line_soft']}; background: {C['bg']}; }}

    /* ---- preview / progress ---- */
    QFrame#PreviewFrame {{
        background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 10px;
    }}
    QLabel#PreviewPh {{ color: {C['ink_mute']}; font-size: 12px; }}
    QLabel#SubPreview {{
        background: {C['bg']}; border: 1px solid {C['line_soft']}; border-radius: 9px;
        padding: 10px;
    }}
    QSlider::groove:horizontal {{ height: 4px; background: {C['line']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {C['accent']}; width: 13px; height: 13px; margin: -5px 0; border-radius: 7px;
    }}
    QSlider::sub-page:horizontal {{ background: {C['accent']}; border-radius: 2px; }}
    QSlider::groove:horizontal:disabled {{ background: {C['line_soft']}; }}
    QSlider::handle:horizontal:disabled {{ background: {C['line']}; }}
    QSlider::sub-page:horizontal:disabled {{ background: {C['line_soft']}; }}
    QProgressBar {{
        background: {C['surface2']}; border: none; border-radius: 3px;
        height: 6px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {C['accent']}; border-radius: 3px; }}
    QTextEdit#Log {{
        background: {C['bg']}; border: 1px solid {C['line_soft']}; border-radius: 8px;
        color: {C['ink_mute']}; font-family: Consolas, monospace; font-size: 11px;
    }}

    /* ---- menus / dialogs ---- */
    QMenuBar {{ background: {C['bg']}; color: {C['ink_dim']}; border-bottom: 1px solid {C['line_soft']}; padding: 2px 6px; }}
    QMenuBar::item {{ background: transparent; padding: 4px 11px; border-radius: 5px; font-size: 12px; }}
    QMenuBar::item:selected {{ background: {C['surface2']}; color: {C['ink']}; }}
    QMenu {{ background: {C['surface2']}; border: 1px solid {C['line']}; border-radius: 8px; padding: 6px; }}
    QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 5px; color: {C['ink_dim']}; }}
    QMenu::item:selected {{ background: {C['accent_dim']}; color: {C['ink']}; }}
    QMenu::separator {{ height: 1px; background: {C['line_soft']}; margin: 6px 8px; }}

    QListWidget {{
        background: {C['bg']}; border: 1px solid {C['line_soft']}; border-radius: 9px;
        padding: 5px; outline: none;
    }}
    QListWidget::item {{
        padding: 8px 10px; border-radius: 6px; color: {C['ink_dim']};
    }}
    QListWidget::item:hover {{ background: {C['surface']}; color: {C['ink']}; }}
    QListWidget::item:selected {{ background: {C['accent_dim']}; color: {C['ink']}; }}

    /* a list you scan rather than read — the scene column in Gen frames. The
       rule above is shared with the library, the narrators and ideas, so this
       one is scoped instead of loosening theirs. */
    /* the × on a poster, and the preview that hovering one puts on screen */
    QPushButton#ShotDrop {{
        padding: 0; border: none; border-radius: 7px;
        background: {C['bg']}; color: {C['ink']};
        font-size: 11px; font-weight: 700;
    }}
    QPushButton#ShotDrop:hover {{ background: {C['accent']}; color: {C['bg']}; }}
    QLabel#Magnifier {{
        background: {C['bg']}; border: 1px solid {C['line']}; border-radius: 8px;
    }}

    /* the quiet row that opens a scene's frames — a control, not a button */
    QPushButton#Disclose {{
        background: transparent; border: none; padding: 1px 2px;
        color: {C['ink_mute']}; font-size: 11px; text-align: left;
    }}
    QPushButton#Disclose:hover {{ color: {C['accent']}; }}

    QListWidget#CompactList {{ padding: 3px; font-size: 11px; }}
    QListWidget#CompactList::item {{ padding: 1px 8px; }}

    QDialog {{ background: {C['surface']}; }}
    QDialog QLabel#DlgTitle {{ font-size: 14px; font-weight: 600; }}
    QFrame#Sep {{ background: {C['line_soft']}; max-height: 1px; border: none; }}
    """
