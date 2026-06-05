from __future__ import annotations

from PIL import Image, ImageDraw

from ancient_empires.rendering.bitmap_font import BitmapFont


DIFFICULTY_TITLE = "Which Level of Difficulty?"
DIFFICULTY_BODY_LINES = (
    "It is best to play the game at",
    "the Explorer level first.",
    "",
    "At the Expert level, the game",
    "is more challenging and you",
    "will recover a different set",
    "of ancient treasures.",
)
DIFFICULTY_OPTIONS = (
    "Explorer Level of Difficulty",
    "Expert Level of Difficulty",
)


class DifficultyDialogRenderer:
    """Render the startup Explorer/Expert dialog using AEPROG's bitmap font.

    The layout mirrors the generic list-dialog engine around 0x7932/0x7964: a
    white modal window over black, 10-pixel text rows, horizontal separators,
    and an inverted highlighted selection row.
    """

    def __init__(self, font: BitmapFont):
        self.font = font

    def render(self, selected: int = 0) -> Image.Image:
        selected = selected % len(DIFFICULTY_OPTIONS)
        image = Image.new("RGBA", (320, 200), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)

        # Coordinates are DOS pixels from the captured original frame divided by
        # two.  The black 1px inner border and light outer border match the menu
        # dialog chrome used by the startup question.
        x0, y0, x1, y1 = 35, 25, 284, 174
        draw.rectangle((x0, y0, x1, y1), fill=(255, 255, 255, 255), outline=(160, 160, 160, 255))
        draw.rectangle((x0 + 3, y0 + 3, x1 - 3, y1 - 3), outline=(0, 0, 0, 255))

        black = (0, 0, 0, 255)
        white = (255, 255, 255, 255)

        self.font.draw_centered(image, 32, DIFFICULTY_TITLE, black)
        draw.line((x0 + 3, 42, x1 - 3, 42), fill=black)

        text_x = 49
        y = 47
        for line in DIFFICULTY_BODY_LINES:
            if line:
                self.font.draw(image, (text_x, y), line, black)
            y += self.font.line_height

        draw.line((x0 + 3, 115, x1 - 3, 115), fill=black)
        option_y = 126
        for index, option in enumerate(DIFFICULTY_OPTIONS):
            if index == selected:
                draw.rectangle((x0 + 5, option_y - 1, x1 - 6, option_y + self.font.line_height), fill=black)
                self.font.draw(image, (text_x, option_y), option, white)
            else:
                self.font.draw(image, (text_x, option_y), option, black)
            option_y += self.font.line_height

        draw.line((x0 + 3, 156, x1 - 3, 156), fill=black)
        esc = "Esc"
        esc_w = self.font.measure(esc) + 8
        esc_x = 103
        esc_y = 162
        draw.rectangle((esc_x - 1, esc_y - 2, esc_x + esc_w, esc_y + self.font.line_height), outline=black)
        self.font.draw(image, (esc_x + 3, esc_y), esc, black)
        self.font.draw(image, (140, esc_y), "to Go Back", black)
        return image
