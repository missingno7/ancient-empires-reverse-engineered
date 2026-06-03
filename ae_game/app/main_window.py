"""Tk presentation shell for the reverse-engineered game."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import copy
import time
import tkinter as tk

from PIL import Image, ImageTk

from ancient_empires.constants import ACTOR_TICK_HZ
from ancient_empires.engine import (
    PlayerController,
    PlayerInput,
    RoomSimulation,
    resolve_room_edge,
)
from ancient_empires.game_data.room_payload import (
    header_exit_door,
    header_object_candidates,
    transition_links_for_room,
)
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.rendering.coordinates import header_exit_door_xy, header_object_xy
from ancient_empires.rendering.game_screen import GameHudState, GameScreenRenderer


REGION_LEVEL_NAMES = ("Near East", "Egypt", "Greece and Rome", "India and China", "Ancient World")
CHAMBER_NUMERALS = ("I", "II", "III", "IV")
EXIT_ENTER_FRAMES = (19, 20, 21, 20, 21, 20)


@dataclass
class _RenderSnapshot:
    room_index: int
    player_x: int
    player_y: int
    actor_positions: dict[int, tuple[int, int]]
    platform_offsets: dict[int, tuple[int, int]]


def hud_indices_for_level(level_index: int) -> tuple[int, int]:
    level_index = max(0, int(level_index))
    return min(4, level_index // 4), min(3, level_index % 4)


def level_display_name(level_index: int) -> str:
    region_index, cavern_index = hud_indices_for_level(level_index)
    return f"{REGION_LEVEL_NAMES[region_index]} {CHAMBER_NUMERALS[cavern_index]}"


class GameWindow:
    def __init__(self, project: AncientEmpiresProject, *, scale: int = 3):
        self.project = project
        self.scale = max(1, int(scale))
        self.root = tk.Tk()
        self.root.title("Ancient Empires")
        self.root.resizable(False, False)

        self.level = project.levels[0]
        self.part_index = 0
        self.room_index = 0
        self.screen_renderer = GameScreenRenderer(project.graphics, project.renderer)
        # The original keeps every room's actors/controls in one persistent
        # table and only re-initialises a room the first time it is entered
        # (load_room at 0x4517 skips reload when the room is already current).
        # Cache one RoomSimulation per room so revisiting pauses-then-resumes
        # rather than restarting.
        self._rooms: dict[tuple[int, int], RoomSimulation] = {}
        self.simulation = self._room_simulation(self.room_index)
        self.player = PlayerController(self.level, self.part_index, self.room_index)
        self.collected_artifacts: set[int] = set()
        self._exit_enter_ticks = 0
        self._exit_target_level_index: int | None = None
        self.show_invisible = False
        self.interpolate_frames = False
        self._keys: set[str] = set()
        self._tick_ms = round(1000 / ACTOR_TICK_HZ)
        self._render_ms = round(1000 / 60)
        self._tick_seconds = 1.0 / ACTOR_TICK_HZ
        self._last_tick_time = time.perf_counter()
        self._previous_render_snapshot: _RenderSnapshot | None = None
        self._current_render_snapshot: _RenderSnapshot | None = None
        self._render_after_id: str | None = None
        self.canvas = tk.Canvas(
            self.root,
            width=320 * self.scale,
            height=200 * self.scale,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.pack()
        self._photo: ImageTk.PhotoImage | None = None
        self._build_menu()
        self.root.bind("<KeyPress>", self._on_key_press)
        self.root.bind("<KeyRelease>", self._on_key_release)
        self.root.focus_force()
        self._current_render_snapshot = self._capture_render_snapshot()
        self._previous_render_snapshot = self._current_render_snapshot
        self._render()
        self._schedule_render_loop()
        self.root.after(self._tick_ms, self._tick)

    def _build_menu(self) -> None:
        """Native dropdown 'Develop' menu for debugging (level jump, etc.)."""
        menubar = tk.Menu(self.root)
        develop = tk.Menu(menubar, tearoff=0)

        levels = tk.Menu(develop, tearoff=0)
        self._level_var = tk.IntVar(value=self.level.index)
        for i, level in enumerate(self.project.levels):
            levels.add_radiobutton(
                label=f"{i + 1}: {level_display_name(i)}",
                value=level.index,
                variable=self._level_var,
                command=lambda i=i: self._select_level(i),
            )
        develop.add_cascade(label="Select Level", menu=levels)

        # Difficulty == the level part: 0 Explorer, 1 Expert.
        parts = tk.Menu(develop, tearoff=0)
        self._part_var = tk.IntVar(value=self.part_index)
        part_names = {0: "Explorer", 1: "Expert"}
        max_parts = max(len(level.parts) for level in self.project.levels)
        for pi in range(max_parts):
            parts.add_radiobutton(
                label=part_names.get(pi, f"Part {pi}"),
                value=pi,
                variable=self._part_var,
                command=lambda pi=pi: self._select_part(pi),
            )
        develop.add_cascade(label="Difficulty", menu=parts)

        self._show_invisible_var = tk.BooleanVar(value=self.show_invisible)
        develop.add_checkbutton(
            label="Show Invisible Blocks",
            variable=self._show_invisible_var,
            command=self._toggle_invisible,
        )
        self._interpolate_frames_var = tk.BooleanVar(value=self.interpolate_frames)
        develop.add_checkbutton(
            label="Frame Interpolation",
            variable=self._interpolate_frames_var,
            command=self._toggle_frame_interpolation,
        )
        # Placeholders for upcoming cheats (god mode, etc.).
        menubar.add_cascade(label="Develop", menu=develop)
        self.root.config(menu=menubar)

    def _toggle_invisible(self) -> None:
        self.show_invisible = bool(self._show_invisible_var.get())
        self._render()

    def _toggle_frame_interpolation(self) -> None:
        self.interpolate_frames = bool(self._interpolate_frames_var.get())
        now = time.perf_counter()
        self._last_tick_time = now
        self._current_render_snapshot = self._capture_render_snapshot()
        self._previous_render_snapshot = self._current_render_snapshot
        self._schedule_render_loop()
        self._render()

    def _select_level(self, level_index: int) -> None:
        self._load(self.project.levels[level_index], self.part_index)

    def _select_part(self, part_index: int) -> None:
        self._load(self.level, part_index)

    def _load(self, level, part_index: int) -> None:
        """(Re)enter a level/part at room 0 with a fresh simulation cache."""
        self.level = level
        self.part_index = min(part_index, len(level.parts) - 1)
        self.room_index = 0
        self._rooms.clear()
        self.simulation = self._room_simulation(self.room_index)
        self.player = PlayerController(self.level, self.part_index, self.room_index)
        self.collected_artifacts.clear()
        self._exit_enter_ticks = 0
        self._exit_target_level_index = None
        self._reset_render_snapshots()
        self.root.focus_force()
        self._render()

    def _on_key_press(self, event: tk.Event) -> None:
        self._keys.add(str(event.keysym).lower())

    def _on_key_release(self, event: tk.Event) -> None:
        self._keys.discard(str(event.keysym).lower())

    def _tick(self) -> None:
        self._previous_render_snapshot = self._current_render_snapshot or self._capture_render_snapshot()
        command = PlayerInput(
            left="left" in self._keys,
            right="right" in self._keys,
            jump="up" in self._keys,
            down="down" in self._keys,
            change_tool="return" in self._keys,
            use_tool="space" in self._keys,
        )
        if self._tick_exit_enter_animation():
            return
        if command.jump and self._try_start_exit_door():
            return
        self.player.tick(command, self.simulation.runtime_tiles())
        self._apply_room_transitions()
        self.simulation.set_player_position(self.player.state.x, self.player.state.y)
        # Walk-onto-button activation (0x3c50) plus the actor VM's scripted
        # triggers (opcode 0x08) inside step() are the real control paths.
        self.simulation.apply_player_object_interaction()
        self._collect_artifacts()
        if self.player.state.fired_laser:
            self.simulation.fire_laser(
                self.player.state.x, self.player.state.y, self.player.state.facing
            )
        self.simulation.step()
        self._last_tick_time = time.perf_counter()
        self._current_render_snapshot = self._capture_render_snapshot()
        if not self.interpolate_frames:
            self._render()
        self.root.after(self._tick_ms, self._tick)

    def _apply_room_transitions(self) -> None:
        links = transition_links_for_room(self.simulation.part, self.room_index)
        if links is None:
            return
        transition = resolve_room_edge(self.player.state, links)
        if transition is None:
            return
        if 0 <= transition.to_room < len(self.simulation.part.rooms):
            self._change_room(transition.to_room)

    def _room_simulation(self, room_index: int) -> RoomSimulation:
        key = (self.part_index, room_index)
        sim = self._rooms.get(key)
        if sim is None:
            sim = RoomSimulation(self.level, self.part_index, room_index)
            self._rooms[key] = sim
        return sim

    def _change_room(self, room_index: int) -> None:
        """Swap the active room, keeping the player's repositioned coordinates.

        The previous room's simulation is left cached so its actor/control state
        is exactly where it was when the player left (paused while away).
        """
        self.room_index = room_index
        self.simulation = self._room_simulation(room_index)
        self.player.room_index = room_index
        self.player.part = self.simulation.part
        self._reset_render_snapshots()

    @staticmethod
    def _player_overlaps(left: int, top: int, width: int, height: int, player) -> bool:
        player_left = player.x
        player_top = player.y
        player_right = player_left + 0x27
        player_bottom = player_top + 0x2F
        return (
            player_right >= left
            and left + width > player_left
            and player_bottom >= top
            and top + height > player_top
        )

    def _configured_artifacts(self) -> set[int]:
        return {cand.index for cand in header_object_candidates(self.simulation.part.header)}

    def _all_artifacts_collected(self) -> bool:
        artifacts = self._configured_artifacts()
        return bool(artifacts) and artifacts <= self.collected_artifacts

    def _collect_artifacts(self) -> None:
        for cand in header_object_candidates(self.simulation.part.header):
            if cand.index in self.collected_artifacts:
                continue
            if cand.room_plus_one != self.room_index + 1:
                continue
            left, top = header_object_xy(cand.x_raw, cand.y_raw)
            if self._player_overlaps(left, top, 16, 16, self.player.state):
                self.collected_artifacts.add(cand.index)

    def _try_start_exit_door(self) -> bool:
        if not self._all_artifacts_collected():
            return False
        door = header_exit_door(self.simulation.part.header)
        if door is None or door.room_index != self.room_index:
            return False
        left, top = header_exit_door_xy(door.x_raw, door.y_raw)
        if not self._player_overlaps(left, top, 46, 33, self.player.state):
            return False
        next_level_index = self.level.index + 1
        if next_level_index >= len(self.project.levels):
            return False
        self._exit_enter_ticks = len(EXIT_ENTER_FRAMES)
        self._exit_target_level_index = next_level_index
        self.player.state.frame = EXIT_ENTER_FRAMES[0]
        self._last_tick_time = time.perf_counter()
        self._current_render_snapshot = self._capture_render_snapshot()
        if not self.interpolate_frames:
            self._render()
        self.root.after(self._tick_ms, self._tick)
        return True

    def _tick_exit_enter_animation(self) -> bool:
        if self._exit_enter_ticks <= 0:
            return False
        frame_index = len(EXIT_ENTER_FRAMES) - self._exit_enter_ticks
        self.player.state.frame = EXIT_ENTER_FRAMES[min(frame_index, len(EXIT_ENTER_FRAMES) - 1)]
        self._exit_enter_ticks -= 1
        if self._exit_enter_ticks <= 0 and self._exit_target_level_index is not None:
            next_level_index = self._exit_target_level_index
            self._exit_target_level_index = None
            self._level_var.set(next_level_index)
            self._load(self.project.levels[next_level_index], self.part_index)
            self.root.after(self._tick_ms, self._tick)
            return True
        self._last_tick_time = time.perf_counter()
        self._current_render_snapshot = self._capture_render_snapshot()
        if not self.interpolate_frames:
            self._render()
        self.root.after(self._tick_ms, self._tick)
        return True

    def _hud_state(self) -> GameHudState:
        region_index, cavern_index = hud_indices_for_level(self.level.index)
        return GameHudState(
            tool_index=self.player.state.tool,
            artifact_pieces=len(self.collected_artifacts),
            region_index=region_index,
            cavern_index=cavern_index,
        )

    def _capture_render_snapshot(self) -> _RenderSnapshot:
        actors = {
            actor.index: (actor.x, actor.y)
            for actor in self.simulation.actors.values()
            if actor.room_index == self.room_index
        }
        platform_offsets = {}
        from ancient_empires.game_data.room_payload import parse_platform_triplets

        for platform in parse_platform_triplets(self.simulation.room):
            if platform.visible:
                platform_offsets[platform.index] = self.simulation.platform_render_offset(platform)
        return _RenderSnapshot(
            room_index=self.room_index,
            player_x=self.player.state.x,
            player_y=self.player.state.y,
            actor_positions=actors,
            platform_offsets=platform_offsets,
        )

    def _reset_render_snapshots(self) -> None:
        snapshot = self._capture_render_snapshot()
        self._previous_render_snapshot = snapshot
        self._current_render_snapshot = snapshot
        self._last_tick_time = time.perf_counter()

    @staticmethod
    def _lerp_int(a: int, b: int, alpha: float) -> int:
        return round(a + (b - a) * alpha)

    @staticmethod
    def _lerp_point(a: tuple[int, int], b: tuple[int, int], alpha: float) -> tuple[int, int]:
        return round(a[0] + (b[0] - a[0]) * alpha), round(a[1] + (b[1] - a[1]) * alpha)

    def _interpolation_alpha(self) -> float:
        if not self.interpolate_frames:
            return 1.0
        return max(0.0, min(1.0, (time.perf_counter() - self._last_tick_time) / self._tick_seconds))

    def _interpolated_player_state(self, alpha: float):
        previous = self._previous_render_snapshot
        current = self._current_render_snapshot
        if not self.interpolate_frames or previous is None or current is None or previous.room_index != current.room_index:
            return self.player.state
        return replace(
            self.player.state,
            x=self._lerp_int(previous.player_x, current.player_x, alpha),
            y=self._lerp_int(previous.player_y, current.player_y, alpha),
        )

    def _interpolated_actors(self, actors, alpha: float):
        previous = self._previous_render_snapshot
        current = self._current_render_snapshot
        if not self.interpolate_frames or previous is None or current is None or previous.room_index != current.room_index:
            return actors
        out = []
        for actor in actors:
            old_xy = previous.actor_positions.get(actor.index)
            new_xy = current.actor_positions.get(actor.index)
            if old_xy is None or new_xy is None:
                out.append(actor)
                continue
            drawn = copy.copy(actor)
            drawn.x, drawn.y = self._lerp_point(old_xy, new_xy, alpha)
            out.append(drawn)
        return out

    def _interpolated_platform_offsets(self, alpha: float) -> dict[int, tuple[int, int]] | None:
        previous = self._previous_render_snapshot
        current = self._current_render_snapshot
        if not self.interpolate_frames or previous is None or current is None or previous.room_index != current.room_index:
            return None
        out: dict[int, tuple[int, int]] = {}
        for index, new_offset in current.platform_offsets.items():
            old_offset = previous.platform_offsets.get(index, new_offset)
            out[index] = self._lerp_point(old_offset, new_offset, alpha)
        return out

    def _schedule_render_loop(self) -> None:
        if not self.interpolate_frames:
            if self._render_after_id is not None:
                self.root.after_cancel(self._render_after_id)
                self._render_after_id = None
            return
        if self._render_after_id is None:
            self._render_after_id = self.root.after(self._render_ms, self._render_loop)

    def _render_loop(self) -> None:
        self._render_after_id = None
        if self.interpolate_frames:
            self._render()
            self._render_after_id = self.root.after(self._render_ms, self._render_loop)

    def _render(self) -> None:
        actors = [
            actor
            for actor in self.simulation.actors.values()
            if actor.room_index == self.room_index
        ]
        alpha = self._interpolation_alpha()
        draw_player = self._interpolated_player_state(alpha)
        draw_actors = self._interpolated_actors(actors, alpha)
        platform_offsets = self._interpolated_platform_offsets(alpha)
        image = self.screen_renderer.render(
            self.level,
            part_index=self.part_index,
            room_index=self.room_index,
            player=draw_player,
            actors=draw_actors,
            simulation=self.simulation,
            show_invisible=self.show_invisible,
            hud=self._hud_state(),
            platform_offsets_override=platform_offsets,
            collected_artifacts=set(self.collected_artifacts),
            show_exit_door=self._all_artifacts_collected(),
        )
        if self.scale != 1:
            image = image.resize(
                (image.width * self.scale, image.height * self.scale),
                Image.Resampling.NEAREST,
            )
        self._photo = ImageTk.PhotoImage(image)
        self.canvas.create_image(0, 0, image=self._photo, anchor=tk.NW)

    def run(self) -> None:
        self.root.mainloop()
