from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from ancient_empires.game_data.graphics import GraphicsSet


MAP_BACKGROUND_ORIGIN = (0, 12)
MAP_ORIGIN = (5, 15)
ANCIENT_WORLD_LEVEL_INDEX = 16



@dataclass(frozen=True)
class MapChoice:
    level_index: int
    label: str
    icon_position: tuple[int, int]
    normal_resource_id: int
    completed_resource_id: int


# AEPROG's map setup loads AE000:028 as the map, AE000:029..036 as the four
# region icons and their completed variants, and AE000:037 as the selector.
# These are full-screen DOS coordinates, matched against the original captured
# map-menu frame.
MAP_CHOICES: tuple[MapChoice, ...] = (
    MapChoice(0, "Near East I", (108, 44), 29, 33),
    MapChoice(4, "Egypt I", (38, 78), 30, 34),
    MapChoice(8, "Greece and Rome I", (38, 25), 31, 35),
    MapChoice(12, "India and China I", (194, 50), 32, 36),
)


class MapScreenRenderer:
    """Render the recovered map-menu screen from the original resource bank."""

    def __init__(self, graphics: GraphicsSet):
        self.graphics = graphics

    def render(self, selected: int = 0, completed_regions: set[int] | frozenset[int] | None = None) -> Image.Image:
        completed_regions = completed_regions or set()
        screen = Image.new("RGBA", (320, 200), (0, 0, 0, 255))
        self._draw_background(screen)
        self._draw_base_map(screen)
        self._draw_region_icons(screen, completed_regions)

        selector = self.graphics.sprite("AE000", 37, 0)
        if selector is not None:
            choice = MAP_CHOICES[selected % len(MAP_CHOICES)]
            screen.alpha_composite(selector.convert("RGBA"), choice.icon_position)
        return screen

    def render_ancient_reveal(self, frame: int, total_frames: int) -> Image.Image:
        """Slide the map upward to reveal AE000:026, matching the original beat."""
        total_frames = max(1, total_frames)
        frame = max(0, min(frame, total_frames))
        screen = Image.new("RGBA", (320, 200), (0, 0, 0, 255))
        self._draw_background(screen)

        progress = frame / total_frames
        map_y = MAP_ORIGIN[1] - round(152 * progress)
        self._draw_base_map(screen, origin=(MAP_ORIGIN[0], map_y))
        return screen

    def render_level_enter_transition(
        self,
        selected: int = 0,
        completed_regions: set[int] | frozenset[int] | None = None,
        frame: int = 0,
        total_frames: int = 1,
    ) -> Image.Image:
        """Simple fade-to-black transition for entering a level from the map."""
        completed_regions = completed_regions or set()
        total_frames = max(1, total_frames)
        frame = max(0, min(frame, total_frames))
        progress = frame / total_frames
        image = self.render(selected, completed_regions)
        overlay = Image.new("RGBA", (320, 200), (0, 0, 0, round(255 * progress)))
        image.alpha_composite(overlay)
        return image

    def _draw_background(self, screen: Image.Image) -> None:
        ancient = self.graphics.sprite("AE000", 26, 0)
        if ancient is not None:
            screen.alpha_composite(ancient.convert("RGBA"), MAP_BACKGROUND_ORIGIN)

    def _draw_base_map(self, screen: Image.Image, *, origin: tuple[int, int] = MAP_ORIGIN) -> None:
        map_panel = self.graphics.sprite("AE000", 28, 0)
        if map_panel is not None:
            screen.alpha_composite(map_panel.convert("RGBA"), origin)

    def _draw_region_icons(self, screen: Image.Image, completed_regions: set[int] | frozenset[int]) -> None:
        for region_index, choice in enumerate(MAP_CHOICES):
            resource_id = choice.completed_resource_id if region_index in completed_regions else choice.normal_resource_id
            icon = self.graphics.sprite("AE000", resource_id, 0)
            if icon is not None:
                screen.alpha_composite(icon.convert("RGBA"), choice.icon_position)
