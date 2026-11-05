# -*- coding: utf-8 -*-
"""今天摸了吗 · 主题 / 柔光渐变背景 / 样式表"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QRadialGradient, QPainterPath
from PySide6.QtWidgets import QWidget

THEMES: dict[str, dict[str, str]] = {
    "aurora": {
        "name": "极光柔光",
        "stops": "#F3F0FF|#FFF1EC|#E8F3FF",
        "glow1": "#C9B8FF", "glow2": "#FFC7AF", "glow3": "#A9D8FF",
        "text": "#202541", "muted": "#565E7A",
        "accent": "#C04219", "accent_soft": "#F6E1D8",
        "accent2": "#4457CC", "accent2_soft": "#DFE5FF",
        "button": "#232945", "button_hover": "#333B60",
        "card": "#FFFFFF", "border": "#FFFFFF",
    },
    "peach": {
        "name": "蜜桃奶油",
        "stops": "#FFF3EC|#FFECE6|#FFF7E9",
        "glow1": "#FFC9AE", "glow2": "#FFD9C0", "glow3": "#FFE6B8",
        "text": "#3A2A28", "muted": "#6B5852",
        "accent": "#B84018", "accent_soft": "#F9DFD2",
        "accent2": "#9E3B58", "accent2_soft": "#F8DDE6",
        "button": "#3B2A2C", "button_hover": "#50383A",
        "card": "#FFFFFF", "border": "#FFFFFF",
    },
    "mint": {
        "name": "薄荷海盐",
        "stops": "#EAF8F4|#EFF6FF|#F3FBF0",
        "glow1": "#A8E6D2", "glow2": "#B9D8FF", "glow3": "#D5F0B8",
        "text": "#1D3735", "muted": "#47635F",
        "accent": "#B1441F", "accent_soft": "#F8DFD3",
        "accent2": "#226B66", "accent2_soft": "#D5F0EA",
        "button": "#1E3B3A", "button_hover": "#2C5451",
        "card": "#FFFFFF", "border": "#FFFFFF",
    },
}


def theme(key: str) -> dict[str, str]:
    return THEMES.get(key, THEMES["aurora"])


# --------------------------------------------------------------------------- #
# 自定义配色：只替换色相，明度 / 饱和度沿用原主题，因此对比度不会被破坏
# --------------------------------------------------------------------------- #
def _hsl(h: float, s: float, l: float) -> str:
    c = QColor.fromHslF((h % 360.0) / 360.0, max(0.0, min(1.0, s)),
                        max(0.0, min(1.0, l)))
    return c.name().upper()


def recolor(color: str, hue: int | None) -> str:
    """把颜色换成指定色相，保留原色的饱和度与明度。"""
    if hue is None or hue < 0:
        return color
    c = QColor(color)
    h, s, l, _a = c.getHslF()
    if h < 0:            # 灰色没有色相，给一个中等饱和度避免变成"没有颜色"
        s = max(s, 0.28)
    return _hsl(hue, s, l)


def palette(key: str, accent_hue: int = -1, accent2_hue: int = -1,
            bg_hue: int = -1) -> dict[str, str]:
    """在主题基础上重算配色。

    * 主色 / 副色：换色相，保留饱和度与明度 → 文字对比度不变；
      `*_soft` 是同一色系的高明度版本，用作浅底 / 选中态。
    * 背景：换色相后把底色压到高明度（近白），光斑提高饱和度，
      保持「柔光渐变」质感，同时避免整窗变成浓烈的纯色块。
    * 按钮色跟随主色但压暗，保证白字仍然清晰。
    """
    t = dict(theme(key))
    if accent_hue >= 0:
        t["accent"] = recolor(t["accent"], accent_hue)
        t["accent_soft"] = recolor(t["accent_soft"], accent_hue)
        t["button"] = _hsl(accent_hue, 0.30, 0.20)
        t["button_hover"] = _hsl(accent_hue, 0.32, 0.28)
    if accent2_hue >= 0:
        t["accent2"] = recolor(t["accent2"], accent2_hue)
        t["accent2_soft"] = recolor(t["accent2_soft"], accent2_hue)
    if bg_hue >= 0:
        stops = t["stops"].split("|")
        # 三档近白底色：同一色相的轻微明度差，形成细腻渐变
        t["stops"] = "|".join([
            _hsl(bg_hue + 8, 0.55, 0.975),
            _hsl(bg_hue - 6, 0.45, 0.968),
            _hsl(bg_hue + 18, 0.50, 0.978),
        ][:len(stops)] or stops)
        t["glow1"] = _hsl(bg_hue + 4, 0.62, 0.86)
        t["glow2"] = _hsl(bg_hue - 12, 0.58, 0.88)
        t["glow3"] = _hsl(bg_hue + 26, 0.55, 0.87)
    return t


def palette_for(cfg, widget: bool = False) -> dict[str, str]:
    """按 Settings 里的配色设置取调色板（主界面 / 小组件各一套）。"""
    from core import effective_hues
    a, a2, bg = effective_hues(cfg, widget=widget)
    return palette(cfg.theme, a, a2, bg)


def ui_font() -> str:
    if sys.platform == "win32":
        return '"Microsoft YaHei UI","Microsoft YaHei","Segoe UI"'
    if sys.platform == "darwin":
        return '"PingFang SC","Helvetica Neue"'
    return '"Noto Sans CJK SC","WenQuanYi Micro Hei","DejaVu Sans"'


def num_font() -> str:
    if sys.platform == "win32":
        return '"Consolas","Cascadia Mono","Microsoft YaHei UI"'
    if sys.platform == "darwin":
        return '"SF Mono","Menlo","PingFang SC"'
    return '"DejaVu Sans Mono","Noto Sans CJK SC"'


def make_font(size: int, bold: bool = False, numbers: bool = False) -> QFont:
    f = QFont()
    family = (num_font() if numbers else ui_font()).split(",")[0].strip('"')
    f.setFamilies([family, "Microsoft YaHei UI", "PingFang SC", "Segoe UI", "sans-serif"])
    f.setPixelSize(size)
    f.setBold(bold)
    return f


class SoftGradient(QWidget):
    """Stripe 风格的柔光渐变背景：线性底色 + 多个低饱和径向光斑。

    刻意不使用纯白底：整体是连续的浅色渐变，卡片用半透明白叠在渐变上。
    """

    def __init__(self, parent: QWidget | None = None, theme_key: str = "aurora",
                 radius: int = 18, glow: bool = True):
        super().__init__(parent)
        self.t = theme(theme_key)
        self.radius = radius
        self.glow = glow
        self.alpha = 1.0          # 背景通透度（1.0 = 不透明）
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_theme(self, key: str) -> None:
        self.t = theme(key)
        self.update()

    def set_palette(self, pal: dict[str, str]) -> None:
        """直接套用一份（可能经过自定义配色推导的）调色板。"""
        self.t = dict(pal)
        self.update()

    def set_alpha(self, value: float) -> None:
        """直接把通透度做进绘制层，跨平台一致；文字子控件不受影响，始终清晰。"""
        self.alpha = min(1.0, max(0.0, float(value)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, w - 1, h - 1, self.radius, self.radius)
        p.setClipPath(path)
        p.setOpacity(self.alpha)

        stops = self.t["stops"].split("|")
        base = QLinearGradient(QPointF(0, 0), QPointF(w, h))
        for i, color in enumerate(stops):
            base.setColorAt(i / max(1, len(stops) - 1), QColor(color))
        p.fillRect(self.rect(), base)

        if self.glow:
            blobs = [
                (0.10, 0.02, 0.85, self.t["glow1"], 0.55),
                (0.95, 0.18, 0.75, self.t["glow2"], 0.45),
                (0.25, 1.00, 0.95, self.t["glow3"], 0.40),
            ]
            for fx, fy, scale, color, alpha in blobs:
                cx, cy = w * fx, h * fy
                r = max(w, h) * scale
                g = QRadialGradient(QPointF(cx, cy), r)
                c = QColor(color)
                c.setAlphaF(alpha)
                g.setColorAt(0, c)
                c2 = QColor(color)
                c2.setAlphaF(0.0)
                g.setColorAt(1, c2)
                p.fillRect(self.rect(), g)
        p.end()


def qss(t: dict[str, str], *, card_alpha: float = 0.44, scale: float = 1.0) -> str:
    """生成 Qt 样式表。scale 用于桌面小组件整体缩放字号。"""
    def px(v: float) -> int:
        return max(8, int(round(v * scale)))

    card_bg = f"rgba(255,255,255,{card_alpha:.2f})"
    return f"""
    QWidget {{ font-family: {ui_font()}; color: {t['text']}; }}
    QLabel {{ background: transparent; }}
    #Card {{
        background: {card_bg};
        border: 1px solid rgba(255,255,255,0.80);
        border-radius: {px(16)}px;
    }}
    #Title {{ font-size: {px(14)}px; font-weight: 600; }}
    #DateLine {{ font-size: {px(13)}px; color: {t['muted']}; }}
    #Status {{ font-size: {px(24)}px; font-weight: 700; color: {t['accent2']}; }}
    #Countdown {{ font-size: {px(13)}px; color: {t['text']}; }}
    #FieldLabel {{ font-size: {px(13)}px; color: {t['muted']}; }}
    #Money {{ font-size: {px(42)}px; font-weight: 700; color: {t['accent']};
              font-family: {num_font()}; letter-spacing: -1px; }}
    #MoneySign {{ font-size: {px(24)}px; font-weight: 700; color: {t['accent']};
                  font-family: {num_font()}; }}
    #Duration {{ font-size: {px(34)}px; font-weight: 700; color: {t['accent2']};
                 font-family: {num_font()}; letter-spacing: -1px; }}
    #Hint {{ font-size: {px(12)}px; color: {t['muted']}; }}
    #Fun {{ font-size: {px(13)}px; color: {t['text']}; }}
    #StatKey {{ font-size: {px(13)}px; color: {t['muted']}; }}
    #StatValue {{ font-size: {px(16)}px; font-weight: 700; color: {t['accent2']};
                  font-family: {num_font()}; }}
    #Brand {{ font-size: {px(12)}px; color: {t['muted']}; }}
    QPushButton#Primary {{
        background: {t['button']}; color: #FFFFFF; border: none;
        border-radius: {px(10)}px; font-size: {px(14)}px; font-weight: 600;
        padding: {px(11)}px {px(14)}px;
    }}
    QPushButton#Primary:hover {{ background: {t['button_hover']}; }}
    QPushButton#Primary:pressed {{ background: {t['button']}; padding-top: {px(12)}px; }}
    QPushButton#Ghost {{
        background: rgba(255,255,255,0.62); color: {t['text']};
        border: 1px solid rgba(255,255,255,0.95);
        border-radius: {px(9)}px; font-size: {px(12)}px; padding: {px(8)}px {px(10)}px;
    }}
    QPushButton#Ghost:hover {{ background: rgba(255,255,255,0.92); }}
    QPushButton#Ghost:checked {{ background: {t['accent2_soft']}; color: {t['accent2']}; }}
    QPushButton#WinBtn {{
        background: transparent; color: {t['muted']}; border: none;
        font-size: {px(13)}px; border-radius: {px(7)}px;
    }}
    QPushButton#WinBtn:hover {{ background: rgba(255,255,255,0.75); color: {t['text']}; }}
    QProgressBar {{
        background: rgba(120,132,170,0.16); border: none;
        border-radius: {px(4)}px; height: {px(8)}px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {t['accent2']}; border-radius: {px(4)}px; }}
    QToolTip {{
        background: {t['button']}; color: #FFFFFF; border: none;
        padding: 5px 8px; border-radius: 6px; font-size: {px(12)}px;
    }}
    /* 键盘焦点必须可见，且不能只靠颜色传达状态 */
    QPushButton:focus, QRadioButton:focus, QCheckBox:focus {{
        outline: 2px solid {t['accent2']};
    }}
    QPushButton:focus:pressed {{ outline: 2px solid {t['accent']}; }}
    """


def settings_qss(t: dict[str, str]) -> str:
    """设置窗口样式（与主体一致的柔光渐变，控件半透明，避免白底突兀）。"""
    s0, s1, s2 = (t["stops"].split("|") + ["#FFFFFF", "#FFFFFF"])[:3]
    gradient = (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                f"stop:0 {s0}, stop:0.52 {s1}, stop:1 {s2})")
    return f"""
    QDialog {{ background: {gradient}; font-family: {ui_font()}; color: {t['text']}; }}
    QLabel {{ background: transparent; font-size: 13px; }}
    QLabel#GroupTitle {{ font-size: 14px; font-weight: 700; color: {t['accent2']}; }}
    QLabel#Help {{ font-size: 12px; color: {t['muted']}; }}
    QGroupBox {{
        background: rgba(255,255,255,0.34);
        border: 1px solid rgba(255,255,255,0.85);
        border-radius: 10px; margin-top: 15px; padding: 10px 10px 8px 10px;
        font-size: 12px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
        left: 12px; padding: 0 5px; color: {t['accent2']}; font-weight: 600; }}
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTimeEdit, QPlainTextEdit {{
        background: rgba(255,255,255,0.76); border: 1px solid rgba(120,132,170,0.22);
        border-radius: 8px; padding: 6px 9px; font-size: 13px; color: {t['text']};
        selection-background-color: {t['accent2_soft']};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus {{
        border: 1px solid {t['accent2']};
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QCheckBox {{ font-size: 13px; spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid rgba(120,132,170,0.4); background: rgba(255,255,255,0.9); }}
    QCheckBox::indicator:checked {{ background: {t['accent2']}; border-color: {t['accent2']}; }}
    QRadioButton {{ font-size: 13px; background: transparent; spacing: 6px; }}
    QTabWidget::pane {{ border: none; background: transparent; }}
    QTabBar::tab {{ background: rgba(255,255,255,0.55); color: {t['muted']};
        padding: 8px 16px; margin-right: 4px; border-top-left-radius: 8px;
        border-top-right-radius: 8px; font-size: 13px; }}
    QTabBar::tab:selected {{ background: rgba(255,255,255,0.95); color: {t['accent2']}; font-weight: 700; }}
    QPushButton {{ background: rgba(255,255,255,0.8); color: {t['text']};
        border: 1px solid rgba(120,132,170,0.25); border-radius: 8px;
        padding: 8px 16px; font-size: 13px; }}
    QPushButton:hover {{ background: #FFFFFF; }}
    QPushButton:focus {{ outline: 2px solid {t['accent2']}; }}
    QPushButton#Save {{ background: {t['button']}; color: #FFFFFF; border: none; font-weight: 600; }}
    QPushButton#Save:hover {{ background: {t['button_hover']}; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: rgba(120,132,170,0.35); border-radius: 4px; }}
    """
