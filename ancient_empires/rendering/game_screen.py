"""Composition of the original 320x200 gameplay screen."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from ..engine.player import PlayerState
from ..game_data.graphics import GraphicsSet
from ..game_data.level_format import Level
from ..game_data.room_payload import header_player_start
from .coordinates import actor_xy
from .room_renderer import RenderOptions, RoomRenderer


SCREEN_WIDTH = 320
SCREEN_HEIGHT = 200
ROOM_ORIGIN = (8, 16)
HUD_ORIGIN = (6, 162)

# The room draw (AEPROG 0x2bc0) blits the AE001:030+region backdrop over a blue
# clear.  The backdrop's palette index 1 pixels are transparent and reveal that
# clear colour, which is VGA palette index 1 = RGB(0, 0, 170); the backdrop's
# own opaque black pixels form the in-field borders.
BACKGROUND_COLOR_INDEX = 0x01
BACKGROUND_COLOR = (0, 0, 170, 255)


@dataclass(frozen=True)
class GameHudState:
    """Values displayed by the recovered AE000:063 HUD routines."""

    tool_index: int = 0
    region_index: int = 0
    cavern_index: int = 0


class GameScreenRenderer:
    """Render the first recovered gameplay presentation layer.

    AEPROG loads resource 0x3f at 0x6fca and blits its first sprite at
    (6, 162) in 0x6fda. The room viewport is copied to (8, 16) during level
    setup. Dynamic HUD sprites follow the calls at 0x7298, 0x7417 and 0x7443.
    """

    def __init__(self, graphics: GraphicsSet, room_renderer: RoomRenderer):
        self.graphics = graphics
        self.room_renderer = room_renderer

    def render(
        self,
        level: Level,
        *,
        part_index: int = 0,
        room_index: int = 0,
        hud: GameHudState | None = None,
        player: PlayerState | None = None,
        actors=None,
        simulation=None,
        show_invisible: bool = False,
        display_mode: str = "vga",
    ) -> Image.Image:
        hud = hud or GameHudState()
        previous_display_mode = self.graphics.display_mode
        self.graphics.set_display_mode(display_mode)
        try:
            screen = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), BACKGROUND_COLOR)
            # Live simulation state (pressed switches + travelled platforms) so
            # the play field reflects what the player has triggered.
            control_overrides = dict(simulation.control_states) if simulation is not None else None
            platform_offsets = self._platform_offsets(simulation, room_index)
            live_room = simulation is not None and room_index == simulation.room_index
            green_block_alternate = (
                {gb.index: gb.at_alternate for gb in simulation.green_blocks} if live_room else None
            )
            green_block_remaining = (
                {gb.index: gb.remaining_sequence for gb in simulation.green_blocks} if live_room else None
            )
            if simulation is not None and room_index == simulation.room_index:
                conveyor_tiles = simulation.runtime_tiles()
                conveyor_frame = (simulation.tick_count // 2) % 4
            else:
                conveyor_tiles = None
                conveyor_frame = 0
            # The play-field backdrop is the AE001 rtype-0x47 image selected by
            # the level's region byte (resource 30 + region), drawn over the blue
            # clear at 0x2bc0.  Picking the correct region/resource is still being
            # recovered (see docs/menu_dialog_system.md), so for now the room is
            # drawn with its own background and only the clear colour is fixed.
            room = self.room_renderer.render_room(
                level,
                room_index,
                RenderOptions(
                    mode="game",
                    zoom=1,
                    grid=False,
                    part_index=part_index,
                    draw_player_start=False,
                    draw_actors=actors is None,
                    control_state_overrides=control_overrides,
                    platform_offsets=platform_offsets,
                    green_block_alternate=green_block_alternate,
                    green_block_remaining=green_block_remaining,
                    conveyor_frame=conveyor_frame,
                    conveyor_tiles=conveyor_tiles,
                    show_invisible=show_invisible,
                    display_mode=display_mode,
                ),
            )
            screen.alpha_composite(room, ROOM_ORIGIN)
            if actors is not None:
                self._draw_live_actors(screen, actors)
            self._draw_player(screen, level, part_index, room_index, player)
            if simulation is not None and getattr(simulation, "laser_ttl", 0) > 0:
                self._draw_laser(screen, simulation.laser_points)
            self._draw_hud(screen, hud)
            return screen
        finally:
            self.graphics.set_display_mode(previous_display_mode)

    @staticmethod
    def _draw_laser(screen: Image.Image, points) -> None:
        """Draw the flashlight beam as a yellow line (AEPROG 0x5e98 dot trail).

        Laser trail coordinates are in the same space as the play field, so each
        point maps straight to a screen pixel.
        """
        if not points:
            return
        draw = ImageDraw.Draw(screen)
        yellow = (255, 255, 85, 255)
        if len(points) == 1:
            draw.point(points[0], fill=yellow)
            return
        for a, b in zip(points, points[1:]):
            draw.line([a, b], fill=yellow, width=2)

    def _draw_player(
        self,
        screen: Image.Image,
        level: Level,
        part_index: int,
        room_index: int,
        player: PlayerState | None,
    ) -> None:
        if player is None:
            part = level.part(part_index)
            start = header_player_start(part.header)
            if start is None or room_index != start.room_index:
                return
            x = start.x_raw * 2
            y = start.y_raw
            frame = 0
            facing = 0
        else:
            x = player.x
            y = player.y
            frame = player.frame
            facing = player.facing

        sprite = self.graphics.sprite("AE000", 4, frame)
        if sprite is None:
            return
        if facing:
            sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

        # The player is drawn into the same offscreen room buffer as objects.
        # Its viewport mapping is recovered in docs/reverse_engineering_notes.md.
        screen.alpha_composite(sprite, (ROOM_ORIGIN[0] + x - 4, ROOM_ORIGIN[1] + y - 16))

    @staticmethod
    def _platform_offsets(simulation, room_index):
        if simulation is None or room_index != simulation.room_index:
            return None
        from ..game_data.room_payload import parse_platform_triplets

        return {
            p.index: simulation.platform_render_offset(p)
            for p in parse_platform_triplets(simulation.room)
            if p.visible
        }

    def _draw_live_actors(self, screen: Image.Image, actors) -> None:
        """Draw simulation actors at their live positions (AEPROG 0x4ef8).

        The room renderer's static actor pass is suppressed when live actors are
        supplied, so each enemy follows its actor-VM position every frame.
        """
        for actor in actors:
            if not getattr(actor, "active", True) or getattr(actor, "hidden", 0):
                continue
            sprite = self.room_renderer.actor_sprite(actor.frame, actor.frame_variant)
            if sprite is None:
                continue
            rx, ry = actor_xy(actor.x, actor.y)
            screen.alpha_composite(sprite, (ROOM_ORIGIN[0] + rx, ROOM_ORIGIN[1] + ry))

    def _draw_hud(self, screen: Image.Image, hud: GameHudState) -> None:
        base = self.graphics.sprite("AE000", 63, 0)
        if base is not None:
            screen.alpha_composite(base, HUD_ORIGIN)

        # AEPROG 0x7298: selected tool sprites 3..5 at (152, 166).
        tool_index = max(0, min(2, int(hud.tool_index)))
        tool = self.graphics.sprite("AE000", 63, 3 + tool_index)
        if tool is not None:
            screen.alpha_composite(tool, (152, 166))

        # AEPROG 0x7417: region sprites 11..15 at (244, 175).
        region_index = max(0, min(4, int(hud.region_index)))
        region = self.graphics.sprite("AE000", 63, 11 + region_index)
        if region is not None:
            screen.alpha_composite(region, (244, 175))

        # AEPROG 0x7443: cavern sprites 16..19, placed after the cavern index.
        cavern_index = max(0, min(3, int(hud.cavern_index)))
        cavern = self.graphics.sprite("AE000", 63, 16 + cavern_index)
        if cavern is not None:
            screen.alpha_composite(cavern, (244 + cavern_index * 16, 186))
