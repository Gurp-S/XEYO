"""XEYO mark — half-block art derived from assets/xeyo-icon-white.png."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

# Rasterized from assets/xeyo-icon-white.png (white glyph on black).
# Half-block cells (▀▄█) keep the X + nested Y silhouette with the center gap.
LOGO_ART = """\
▄▄▄▄▄▄▄            ▄▄▄▄▄▄▄
 ▀██████         ▄██████▀
   ▀█████▄     ▄██████▀
     ▀█████▄  ██████▀
       ▀█████▄▀███▀
         ▀█████▄▀
        ▄█▄█████
      ▄█████████
    ▄█████▀█████
   ▀▀▀▀▀▀▀ ▀▀▀▀▀\
"""

# Compact 1-glyph stand-in for inline titles (panel chrome).
LOGO_GLYPH = "Ӿ"


def logo_text(*, style: str = "bold bright_white") -> Text:
	return Text(LOGO_ART, style=style)


def identity_block(
	*,
	accent: str = "cyan",
	muted: str = "dim",
) -> Table:
	"""Wordmark + 'I am XEYO' tagline (right of the icon)."""
	grid = Table.grid(padding=(0, 0))
	grid.add_column()
	title = Text()
	title.append("XEYO", style=f"bold {accent}")
	grid.add_row(title)
	tag = Text()
	tag.append("I am XEYO", style=f"bold {accent}")
	grid.add_row(tag)
	grid.add_row(Text("coding agent", style=muted))
	return grid


def logo_with_identity(
	*,
	accent: str = "cyan",
	muted: str = "dim",
	logo_style: str = "bold bright_white",
) -> Table:
	"""Icon art + identity column — primary startup brand lockup."""
	row = Table.grid(padding=(0, 3))
	row.add_column(no_wrap=True)
	row.add_column(vertical="middle")
	row.add_row(logo_text(style=logo_style), identity_block(accent=accent, muted=muted))
	return row


def banner_body(
	meta: RenderableType,
	*,
	accent: str = "cyan",
	muted: str = "dim",
) -> Group:
	"""Full banner: logo lockup above session meta."""
	return Group(
		logo_with_identity(accent=accent, muted=muted),
		Text(""),
		meta,
	)
