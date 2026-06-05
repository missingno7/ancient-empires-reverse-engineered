"""Tk presentation shell for the reverse-engineered game."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import copy
import time
import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from ancient_empires.constants import (
    ACTOR_TICK_HZ,
    hud_indices_for_level,
    level_display_name,
)
from ancient_empires.engine.answer_puzzle import (
    AnswerPuzzleState,
    answer_room_player_start,
    parse_answer_puzzle_room,
)
from ancient_empires.engine.artifact_puzzle import ArtifactPuzzleState
from ancient_empires.engine import (
    PlayerController,
    PlayerInput,
    RoomSimulation,
    resolve_room_edge,
)
from ancient_empires.engine.player import TOOL_IMMORTALITY, load_player_face_boxes, player_face_box
from ancient_empires.game_data.room_payload import (
    HeaderExitDoor,
    header_exit_door,
    header_object_candidates,
    part_apple_marker,
    transition_links_for_room,
)
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.rendering.artifact_puzzle_screen import ArtifactPuzzleScreenRenderer
from ancient_empires.rendering.answer_puzzle_screen import AnswerPuzzleScreenRenderer
from ancient_empires.rendering.bitmap_font import BitmapFont
from ancient_empires.rendering.dialog_screen import DifficultyDialogRenderer
from ancient_empires.rendering.game_screen import GameHudState, GameScreenRenderer
from ancient_empires.rendering.map_screen import ANCIENT_WORLD_LEVEL_INDEX, MAP_CHOICES, MapScreenRenderer
from ae_game.app.audio_engine import GameAudioEngine


# Exit-door entry animation (AEPROG 0x233e): three back-to-back 4-step phases.
#   open : door frames 1->4 while the player stands at the doorway
#   enter: door held open (frame 4) while the player walks in (frames 12->15)
#   close: door frames 3->0 with the player gone
EXIT_OPEN_DOOR_FRAMES = (1, 2, 3, 4)
EXIT_ENTER_PLAYER_FRAMES = (12, 13, 14, 15)
EXIT_CLOSE_DOOR_FRAMES = (3, 2, 1, 0)
EXIT_ANIMATION_STEPS = (
    len(EXIT_OPEN_DOOR_FRAMES) + len(EXIT_ENTER_PLAYER_FRAMES) + len(EXIT_CLOSE_DOOR_FRAMES)
)
ARTIFACT_COMPLETE_FRAMES = (16, 17, 18, 19, 18, 19)
ANCIENT_REVEAL_FRAMES = 24
MAP_LEVEL_TRANSITION_FRAMES = 18
CROSSFADE_FRAMES = 12

# Sentinel player-frame returned by exit_animation_step for the opening phase,
# meaning "keep the player's current standing frame".
EXIT_KEEP_PLAYER_FRAME = -1

# Frame-interpolation guard: a per-axis jump larger than this (pixels) between
# two simulation ticks is treated as a teleport/reset (e.g. a projectile
# snapping back to its spawn) and is drawn instantly rather than smoothed.
INTERPOLATION_SNAP_DISTANCE = 48

# Player health (AEPROG DS:0xb82): five bar segments, starts full.
ENERGY_MAX = 4
# play_sound id used when the player is hit (AEPROG hurt path 0x445e).
SFX_HURT = 1
# Laser: 0x14 fires a beam, 0x17 is the blocked/cooldown click (AEPROG 0x4214).
SFX_LASER = 0x14
SFX_LASER_BLOCKED = 0x17
# Immortality tool: 0x00 on activation, 0x11 when no uses remain (AEPROG 0x41fa/0x4200).
SFX_IMMORTALITY = 0x00
SFX_IMMORTALITY_DENIED = 0x11
# Collecting an artifact piece / apple (AEPROG 0x3ba2 play_sound 2).
SFX_PICKUP = 0x02
# Post-hit state, AEPROG player draw 0x437c: the hurt timer starts at 0x1e and
# counts down; while it is above 0x1a the player shows the hurt frame, below
# that it blinks (drawn only on odd ticks), and the whole window is invulnerable.
HURT_INVULN_TICKS = 0x1E
HURT_ANIM_THRESHOLD = 0x1A
HURT_FRAME = 22            # AE000:004:22 (sprite offset 0x39ec)
# Immortality tool (AEPROG): DS:0x72c timer, DS:0xb80 uses (4/level); the halo
# AE000:004:23 is drawn over the player while active (0x43e6).
IMMORTALITY_TICKS = 0x3A
IMMORTALITY_USES = 4
HALO_FRAME = 23


def exit_animation_step(step: int) -> tuple[int, int | None]:
    """Return ``(door_frame, player_frame)`` for entry-animation step 0..11.

    ``player_frame`` is ``None`` when the player must be hidden (door closing)
    and ``EXIT_KEEP_PLAYER_FRAME`` when it should keep its current standing
    frame (door opening).  Mirrors the three phases of AEPROG 0x233e.
    """
    n_open = len(EXIT_OPEN_DOOR_FRAMES)
    n_enter = len(EXIT_ENTER_PLAYER_FRAMES)
    if step < n_open:
        return EXIT_OPEN_DOOR_FRAMES[step], EXIT_KEEP_PLAYER_FRAME
    if step < n_open + n_enter:
        return 4, EXIT_ENTER_PLAYER_FRAMES[step - n_open]
    return EXIT_CLOSE_DOOR_FRAMES[step - n_open - n_enter], None


@dataclass
class _RenderSnapshot:
    room_index: int
    player_x: int
    player_y: int
    actor_positions: dict[int, tuple[int, int]]
    platform_offsets: dict[int, tuple[int, int]]




def player_aligned_with_exit_door(player, door) -> bool:
    """AEPROG 0x3cc8: the player's anchor must be directly in front of a door.

    The runtime door slot is built at 0x2d9f from header bytes 5/6/7: room
    (0x4377), x (0x4378, stored ``<<1`` so ``x_raw*2``) and y (0x4379, stored
    as-is).  The trigger loop at 0x3cc8 then accepts the player when
    ``|player.x - x_raw*2| <= 2`` and ``y_raw <= player.y <= y_raw + 0x10``.
    The loop is gated only by the held Up-key (DS:0B68) and door count
    (DS:0722); it does not reject ladder, jump or fall state.  This narrow box
    is what stops a nearby rope or platform from activating the door.

    Our ``PlayerController`` grounds the player a pixel or two above the floor
    line the original used as ``y_raw`` (verified: the player rests at
    ``y_raw - 1`` / ``y_raw - 2`` directly in front of every reachable exit
    door).  We absorb that collision-anchor difference with a small slack on
    the upper edge so a standing player actually lands inside the box.
    """
    door_x = door.x_raw * 2
    door_y = door.y_raw
    return (
        door_x - 2 <= player.x <= door_x + 2
        and door_y - 4 <= player.y <= door_y + 0x10
    )


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
        self.scene = "difficulty"
        self.difficulty_selection = 0
        self.map_selection = 0
        self.completed_levels: set[int] = set()
        self._ancient_reveal_frame = 0
        self._map_transition_frame = 0
        self._map_transition_level_index: int | None = None
        self._crossfade_frame = 0
        self._crossfade_source: Image.Image | None = None
        self._crossfade_target: Image.Image | None = None
        self._crossfade_finish: Callable[[], None] | None = None
        self.screen_renderer = GameScreenRenderer(project.graphics, project.renderer)
        self.map_renderer = MapScreenRenderer(project.graphics)
        if project.ae000 is None:
            raise ValueError("AE000.DAT is required for the original menu font")
        self.dialog_renderer = DifficultyDialogRenderer(BitmapFont.from_resource(project.ae000[0].decoded))
        self.puzzle_renderer = ArtifactPuzzleScreenRenderer(project.graphics)
        self.answer_puzzle_renderer = AnswerPuzzleScreenRenderer(
            project.graphics,
            self.screen_renderer,
            project.ae001[20].decoded,
        )
        # The original keeps every room's actors/controls in one persistent
        # table and only re-initialises a room the first time it is entered
        # (load_room at 0x4517 skips reload when the room is already current).
        # Cache one RoomSimulation per room so revisiting pauses-then-resumes
        # rather than restarting.
        self._rooms: dict[tuple[int, int], RoomSimulation] = {}
        self.simulation = self._room_simulation(self.room_index)
        self.player = PlayerController(self.level, self.part_index, self.room_index)
        self.collected_artifacts: set[int] = set()
        # Apples already eaten this level, keyed by room index (one apple/room).
        self.collected_apples: set[int] = set()
        self.god_mode = False
        # Post-hit invulnerability/blink countdown (AEPROG hurt window 0x1e).
        self._hurt_cooldown = 0
        # Immortality tool: per-level use count and active invulnerability timer.
        self.immortality_uses = IMMORTALITY_USES
        self._invuln_timer = 0
        # Per-frame player collision boxes for the actor-contact test (DS:0x79E).
        self._player_face_boxes = load_player_face_boxes(project.exe)
        self._prev_use_tool = False
        self.artifact_puzzle_solved = False
        self.artifact_puzzle: ArtifactPuzzleState | None = None
        self.answer_puzzle: AnswerPuzzleState | None = None
        self.answer_player: PlayerController | None = None
        self.answer_room = parse_answer_puzzle_room(project.ae001[20].decoded)
        self._answer_exit_ticks = 0
        self._artifact_complete_ticks = 0
        self._exit_enter_ticks = 0
        self._exit_door_frame = 0
        self._exit_player_start_frame = 0
        self._exit_player_hidden = False
        self._exit_door_x = 0
        self._exit_door_y = 0
        self._answer_player_hidden = False
        self._exit_target_level_index: int | None = None
        self.show_invisible = False
        self.interpolate_frames = False
        self.sound_enabled = True
        self.music_enabled = True
        self.audio = GameAudioEngine(project)
        self._keys: set[str] = set()
        self._previous_keys: set[str] = set()
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
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.focus_force()
        self._current_render_snapshot = self._capture_render_snapshot()
        self._previous_render_snapshot = self._current_render_snapshot
        self._render()
        self._schedule_render_loop()
        self.root.after(self._tick_ms, self._tick)

    def _start_level_music(self) -> None:
        self.audio.play_level_music(self.level.index)

    def _on_close(self) -> None:
        self.audio.shutdown()
        self.root.destroy()

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
        self._god_mode_var = tk.BooleanVar(value=self.god_mode)
        develop.add_checkbutton(
            label="God Mode",
            variable=self._god_mode_var,
            command=self._toggle_god_mode,
        )
        develop.add_separator()
        develop.add_command(
            label="Collect All Artifact Pieces",
            command=self._collect_all_artifacts,
        )
        develop.add_command(
            label="End Level: Answer Puzzle",
            command=self._develop_answer_puzzle,
        )
        menubar.add_cascade(label="Develop", menu=develop)

        view = tk.Menu(menubar, tearoff=0)
        self._interpolate_frames_var = tk.BooleanVar(value=self.interpolate_frames)
        view.add_checkbutton(
            label="Frame Interpolation",
            variable=self._interpolate_frames_var,
            command=self._toggle_frame_interpolation,
        )
        menubar.add_cascade(label="View", menu=view)

        settings = tk.Menu(menubar, tearoff=0)
        self._sound_enabled_var = tk.BooleanVar(value=self.sound_enabled)
        settings.add_checkbutton(
            label="Sound",
            variable=self._sound_enabled_var,
            command=self._toggle_sound,
        )
        self._music_enabled_var = tk.BooleanVar(value=self.music_enabled)
        settings.add_checkbutton(
            label="Music",
            variable=self._music_enabled_var,
            command=self._toggle_music,
        )
        settings.add_separator()
        # Sound-card (OPL) music is the default; uncheck for the PC-speaker mix.
        self._soundcard_music_var = tk.BooleanVar(value=self.audio.music_mode() == "soundcard")
        settings.add_checkbutton(
            label="Sound Card Music",
            variable=self._soundcard_music_var,
            command=self._toggle_music_mode,
        )
        menubar.add_cascade(label="Settings", menu=settings)

        self.root.config(menu=menubar)

    def _toggle_invisible(self) -> None:
        self.show_invisible = bool(self._show_invisible_var.get())
        self._render()

    def _toggle_sound(self) -> None:
        self.sound_enabled = bool(self._sound_enabled_var.get())
        self.audio.set_sound_enabled(self.sound_enabled)

    def _toggle_music(self) -> None:
        self.music_enabled = bool(self._music_enabled_var.get())
        self.audio.set_music_enabled(self.music_enabled)

    def _toggle_music_mode(self) -> None:
        mode = "soundcard" if self._soundcard_music_var.get() else "pcspeaker"
        if self.scene == "map":
            self.audio.set_music_mode(mode)
            self.audio.play_map_music()
        else:
            self.audio.set_music_mode(mode, self.level.index)

    def _toggle_god_mode(self) -> None:
        self.god_mode = bool(self._god_mode_var.get())
        if self.god_mode:
            self.player.state.energy = ENERGY_MAX
            self._hurt_cooldown = 0
            self._render()

    def _toggle_frame_interpolation(self) -> None:
        self.interpolate_frames = bool(self._interpolate_frames_var.get())
        now = time.perf_counter()
        self._last_tick_time = now
        self._current_render_snapshot = self._capture_render_snapshot()
        self._previous_render_snapshot = self._current_render_snapshot
        self._schedule_render_loop()
        self._render()

    def _collect_all_artifacts(self) -> None:
        if self.artifact_puzzle_solved or self.artifact_puzzle is not None:
            return
        self.collected_artifacts = self._configured_artifacts()
        self.root.focus_force()
        self._render()

    def _develop_answer_puzzle(self) -> None:
        next_level_index = self.level.index + 1
        if next_level_index >= len(self.project.levels):
            return
        self._exit_target_level_index = next_level_index
        self._start_answer_puzzle()

    def _select_level(self, level_index: int) -> None:
        self.scene = "game"
        self._load(self.project.levels[level_index], self.part_index)

    def _select_part(self, part_index: int) -> None:
        self.scene = "game"
        self._load(self.level, part_index)

    def _completed_map_regions_for_levels(self, completed_levels: set[int]) -> set[int]:
        regions: set[int] = set()
        for region_index, choice in enumerate(MAP_CHOICES):
            start = choice.level_index
            if all(level_index in completed_levels for level_index in range(start, start + 4)):
                regions.add(region_index)
        return regions

    def _selectable_map_regions(self, completed_regions: set[int] | None = None) -> list[int]:
        completed = self._completed_map_regions() if completed_regions is None else set(completed_regions)
        return [index for index in range(len(MAP_CHOICES)) if index not in completed]

    def _normalized_map_selection(self, preferred: int | None = None, completed_regions: set[int] | None = None) -> int:
        preferred = self.map_selection if preferred is None else preferred
        selectable = self._selectable_map_regions(completed_regions)
        if not selectable:
            return max(0, min(preferred, len(MAP_CHOICES) - 1))
        if preferred in selectable:
            return preferred
        for index in selectable:
            if index > preferred:
                return index
        return selectable[0]

    def _map_image(
        self,
        *,
        selected: int | None = None,
        completed_regions: set[int] | None = None,
    ) -> Image.Image:
        completed = self._completed_map_regions() if completed_regions is None else set(completed_regions)
        chosen = self._normalized_map_selection(selected, completed)
        return self.map_renderer.render(chosen, completed)

    def _hud_state_for_preview(self, level_index: int, player_state) -> GameHudState:
        region_index, cavern_index = hud_indices_for_level(level_index)
        return GameHudState(
            tool_index=player_state.tool,
            artifact_pieces=0,
            invulnerability_uses=IMMORTALITY_USES,
            energy=player_state.energy,
            region_index=region_index,
            cavern_index=cavern_index,
        )

    def _render_current_game_image(self) -> Image.Image:
        actors = [
            actor
            for actor in self.simulation.actors.values()
            if actor.room_index == self.room_index
        ]
        frame_override, blink_off, halo = self._player_draw_state()
        return self.screen_renderer.render(
            self.level,
            part_index=self.part_index,
            room_index=self.room_index,
            player=self.player.state,
            actors=actors,
            simulation=self.simulation,
            show_invisible=self.show_invisible,
            hud=self._hud_state(),
            collected_artifacts=set(self.collected_artifacts),
            apple_collected=self._apple_collected(),
            show_exit_door=self.artifact_puzzle_solved,
            exit_door_frame=self._exit_door_frame,
            show_player=not self._exit_player_hidden and not blink_off,
            player_frame_override=frame_override,
            player_halo=halo,
        )

    def _preview_level_start_image(self, level_index: int) -> Image.Image:
        level = self.project.levels[level_index]
        room_index = 0
        simulation = RoomSimulation(level, self.part_index, room_index)
        player = PlayerController(level, self.part_index, room_index).state
        actors = [actor for actor in simulation.actors.values() if actor.room_index == room_index]
        return self.screen_renderer.render(
            level,
            part_index=self.part_index,
            room_index=room_index,
            player=player,
            actors=actors,
            simulation=simulation,
            hud=self._hud_state_for_preview(level.index, player),
            collected_artifacts=set(),
            apple_collected=False,
            show_exit_door=False,
            show_player=True,
        )

    def _render_current_answer_puzzle_image(self) -> Image.Image:
        if self.answer_puzzle is None:
            raise RuntimeError("Answer puzzle is not active")
        return self.answer_puzzle_renderer.render(
            self.answer_puzzle,
            level=self.level,
            part_index=self.part_index,
            hud=self._hud_state(),
            show_player=not self._answer_player_hidden,
        )

    def _prepare_answer_puzzle_state(self) -> tuple[AnswerPuzzleState, PlayerController]:
        puzzle = AnswerPuzzleState(
            self.project.exe,
            level_index=self.level.index,
            expert=self.part_index == 1,
            theme=self.level.part(self.part_index).theme,
        )
        start_x, start_y = answer_room_player_start(self.project.ae001[20].decoded)
        puzzle.player.x = start_x
        puzzle.player.y = start_y
        controller = PlayerController(self.level, self.part_index, 0)
        controller.state = puzzle.player
        return puzzle, controller

    def _render_answer_puzzle_image_for(self, puzzle: AnswerPuzzleState, *, show_player: bool = True) -> Image.Image:
        return self.answer_puzzle_renderer.render(
            puzzle,
            level=self.level,
            part_index=self.part_index,
            hud=self._hud_state(),
            show_player=show_player,
        )

    def _start_crossfade(self, source: Image.Image, target: Image.Image, on_finish: Callable[[], None]) -> None:
        self.scene = "crossfade"
        self._crossfade_frame = 0
        self._crossfade_source = source.convert("RGBA")
        self._crossfade_target = target.convert("RGBA")
        self._crossfade_finish = on_finish
        self._render()

    def _load(self, level, part_index: int) -> None:
        """(Re)enter a level/part at room 0 with a fresh simulation cache."""
        self.level = level
        self.part_index = min(part_index, len(level.parts) - 1)
        self.room_index = 0
        self._rooms.clear()
        self.simulation = self._room_simulation(self.room_index)
        self.player = PlayerController(self.level, self.part_index, self.room_index)
        self.collected_artifacts.clear()
        self.collected_apples.clear()
        self._hurt_cooldown = 0
        self.immortality_uses = IMMORTALITY_USES
        self._invuln_timer = 0
        self.artifact_puzzle_solved = False
        self.artifact_puzzle = None
        self.answer_puzzle = None
        self.answer_player = None
        self._answer_exit_ticks = 0
        self._artifact_complete_ticks = 0
        self._exit_enter_ticks = 0
        self._exit_door_frame = 0
        self._exit_player_start_frame = 0
        self._exit_player_hidden = False
        self._exit_door_x = 0
        self._exit_door_y = 0
        self._answer_player_hidden = False
        self._exit_target_level_index = None
        self._reset_render_snapshots()
        self.root.focus_force()
        self._render()
        self._start_level_music()

    def _on_key_press(self, event: tk.Event) -> None:
        key = str(event.keysym).lower()
        self._keys.add(key)
        if self.scene == "difficulty":
            self._handle_difficulty_key(key)
            return
        if self.scene == "map":
            self._handle_map_key(key)
            return
        # The artifact-assembly puzzle is cursor-driven, so handle its keys on
        # the key event itself (DOS is event-driven).  Sampling once per ~100ms
        # tick dropped quick taps that were pressed and released between ticks.
        if self.artifact_puzzle is not None:
            self._handle_artifact_puzzle_key(key)

    def _on_key_release(self, event: tk.Event) -> None:
        self._keys.discard(str(event.keysym).lower())

    def _handle_artifact_puzzle_key(self, key: str) -> None:
        puzzle = self.artifact_puzzle
        if puzzle is None:
            return
        if key == "left":
            puzzle.move_cursor(0, -1)
        elif key == "right":
            puzzle.move_cursor(0, 1)
        elif key == "up":
            puzzle.move_cursor(-1, 0)
        elif key == "down":
            puzzle.move_cursor(1, 0)
        elif key == "f":
            puzzle.flip_held_piece()
        elif key == "return":
            puzzle.take_or_drop()
        else:
            return
        if puzzle.solved:
            self.artifact_puzzle_solved = True
            self.artifact_puzzle = None
            self._reset_render_snapshots()
        self._render()

    def _handle_difficulty_key(self, key: str) -> None:
        if key in {"up", "down", "left", "right"}:
            self.difficulty_selection = 1 - self.difficulty_selection
            self._render()
        elif key == "return":
            self.part_index = self.difficulty_selection
            self._part_var.set(self.part_index)
            self.scene = "map"
            self.audio.play_map_music()
            self._render()
        elif key == "escape":
            self._on_close()

    def _handle_map_key(self, key: str) -> None:
        if self._all_normal_regions_completed():
            return
        completed_regions = self._completed_map_regions()
        selectable = self._selectable_map_regions(completed_regions)
        if not selectable:
            return
        self.map_selection = self._normalized_map_selection(self.map_selection, completed_regions)
        current_index = selectable.index(self.map_selection)
        if key in {"left", "up"}:
            self.map_selection = selectable[(current_index - 1) % len(selectable)]
            self._render()
        elif key in {"right", "down"}:
            self.map_selection = selectable[(current_index + 1) % len(selectable)]
            self._render()
        elif key == "return":
            choice = MAP_CHOICES[self.map_selection]
            self._start_map_level_transition(choice.level_index)

    def _completed_map_regions(self) -> set[int]:
        return self._completed_map_regions_for_levels(self.completed_levels)

    def _start_map_level_transition(self, level_index: int) -> None:
        source = self._map_image(selected=self.map_selection)
        target = self._preview_level_start_image(level_index)

        def finish() -> None:
            self._crossfade_source = None
            self._crossfade_target = None
            self._crossfade_finish = None
            self.scene = "game"
            self._level_var.set(level_index)
            self._load(self.project.levels[level_index], self.part_index)

        self._start_crossfade(source, target, finish)

    def _finish_map_level_transition(self) -> None:
        level_index = self._map_transition_level_index
        self._map_transition_level_index = None
        self._map_transition_frame = 0
        if level_index is None:
            self.scene = "map"
            self._render()
            return
        self.scene = "game"
        self._level_var.set(level_index)
        self._load(self.project.levels[level_index], self.part_index)

    def _all_normal_regions_completed(self) -> bool:
        return len(self._completed_map_regions()) == len(MAP_CHOICES)

    def _return_to_map_or_ancient_world(self) -> None:
        self.answer_puzzle = None
        self.answer_player = None
        self._exit_target_level_index = None
        self._answer_exit_ticks = 0
        self._map_transition_frame = 0
        self._map_transition_level_index = None
        if self._all_normal_regions_completed() and len(self.project.levels) > ANCIENT_WORLD_LEVEL_INDEX:
            self.scene = "ancient_reveal"
            self._ancient_reveal_frame = 0
        else:
            self.scene = "map"
            self.map_selection = self._normalized_map_selection(min(self.map_selection, len(MAP_CHOICES) - 1))
            self.audio.play_map_music()
        self._reset_render_snapshots()
        self.root.focus_force()
        self._render()

    def _complete_current_level(self) -> None:
        self.completed_levels.add(self.level.index)
        if self.level.index < ANCIENT_WORLD_LEVEL_INDEX and self.level.index % 4 == 3:
            self._return_to_map_or_ancient_world()
            return

        next_level_index = self._exit_target_level_index
        if next_level_index is None or next_level_index >= len(self.project.levels):
            self._return_to_map_or_ancient_world()
            return
        self._exit_target_level_index = None
        self.answer_puzzle = None
        self.answer_player = None
        self._level_var.set(next_level_index)
        self.scene = "game"
        self._load(self.project.levels[next_level_index], self.part_index)

    def _tick_ancient_reveal(self) -> None:
        self._ancient_reveal_frame += 1
        if self._ancient_reveal_frame >= ANCIENT_REVEAL_FRAMES:
            self.scene = "game"
            self._level_var.set(ANCIENT_WORLD_LEVEL_INDEX)
            self._load(self.project.levels[ANCIENT_WORLD_LEVEL_INDEX], self.part_index)
            self.root.after(self._tick_ms, self._tick)
            return
        self._render()
        self.root.after(self._tick_ms, self._tick)

    def _tick_map_transition(self) -> None:
        self._map_transition_frame += 1
        if self._map_transition_frame >= MAP_LEVEL_TRANSITION_FRAMES:
            self._finish_map_level_transition()
            self.root.after(self._tick_ms, self._tick)
            return
        self._render()
        self.root.after(self._tick_ms, self._tick)

    def _tick_crossfade(self) -> None:
        self._crossfade_frame += 1
        if self._crossfade_frame >= CROSSFADE_FRAMES:
            finish = self._crossfade_finish
            if finish is not None:
                finish()
            self.root.after(self._tick_ms, self._tick)
            return
        self._render()
        self.root.after(self._tick_ms, self._tick)

    def _tick(self) -> None:
        if self.scene in {"difficulty", "map"}:
            self.root.after(self._tick_ms, self._tick)
            return
        if self.scene == "ancient_reveal":
            self._tick_ancient_reveal()
            return
        if self.scene == "map_transition":
            self._tick_map_transition()
            return
        if self.scene == "crossfade":
            self._tick_crossfade()
            return
        self._previous_render_snapshot = self._current_render_snapshot or self._capture_render_snapshot()
        if self.artifact_puzzle is not None:
            self._tick_artifact_puzzle()
            return
        if self.answer_puzzle is not None:
            self._tick_answer_puzzle()
            return
        if self._tick_artifact_complete_animation():
            return
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
        self._advance_invuln_timers()
        use_tool_edge = command.use_tool and not self._prev_use_tool
        self._prev_use_tool = command.use_tool
        if use_tool_edge and self.player.state.tool == TOOL_IMMORTALITY:
            self._activate_immortality()
        self.player.tick(command, self.simulation.runtime_tiles())
        self._apply_room_transitions()
        self.simulation.set_player_position(self.player.state.x, self.player.state.y)
        # Walk-onto-button activation (0x3c50) plus the actor VM's scripted
        # triggers (opcode 0x08) inside step() are the real control paths.
        self.simulation.apply_player_object_interaction()
        self._collect_artifacts()
        if self._try_start_artifact_puzzle():
            return
        if self.player.state.fired_laser:
            emitted = self.simulation.fire_laser(
                self.player.state.x, self.player.state.y, self.player.state.facing
            )
            # AEPROG 0x4214: 0x14 when a beam actually fires, 0x17 while the
            # laser is still on cooldown (DS:08FE set).
            self.player.pending_sounds.append(SFX_LASER if emitted else SFX_LASER_BLOCKED)
        self.simulation.step()
        self._collect_apple()
        self._apply_enemy_contact()
        self._drain_sounds()
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
            if self.simulation.player_pickup_overlaps(cand.x_raw, cand.y_raw):
                self.collected_artifacts.add(cand.index)
                self.player.pending_sounds.append(SFX_PICKUP)

    def _apple_collected(self) -> bool:
        return self.room_index in self.collected_apples

    def _collect_apple(self) -> None:
        """Red apple pickup restores full energy (AEPROG object type 7, 0x3bc2
        calls change_energy(+4))."""
        if self._apple_collected():
            return
        marker = part_apple_marker(self.simulation.part, self.room_index)
        if marker is None:
            return
        if self.simulation.player_pickup_overlaps(marker.x_raw, marker.y_raw):
            self.collected_apples.add(self.room_index)
            self.player.state.energy = ENERGY_MAX
            self.player.pending_sounds.append(SFX_PICKUP)

    def _advance_invuln_timers(self) -> None:
        """AEPROG 0x437c/0x43f8 decrement the hurt and immortality timers once
        per player tick."""
        if self._hurt_cooldown > 0:
            self._hurt_cooldown -= 1
        if self._invuln_timer > 0:
            self._invuln_timer -= 1

    def _activate_immortality(self) -> None:
        """Immortality tool (AEPROG 0x41d8): only when not already invulnerable;
        spends one of the level's uses and grants a 0x3a-tick halo state.  With
        no uses left the original just plays the 'denied' SFX."""
        if self._invuln_timer > 0:
            return
        if self.immortality_uses <= 0:
            self.player.pending_sounds.append(SFX_IMMORTALITY_DENIED)
            return
        self.immortality_uses -= 1
        self._invuln_timer = IMMORTALITY_TICKS
        self.player.pending_sounds.append(SFX_IMMORTALITY)

    def _actor_face_box(self, actor) -> tuple[int, int, int, int] | None:
        """Actor collision box (x_near, y_near, x_far, y_far) relative to its
        anchor.  AEPROG builds this table (DS:0x40D4) at load from the sprite
        bitmaps, so we use each frame's tight non-transparent bounds."""
        sprite = self.screen_renderer.room_renderer.actor_sprite(actor.frame, actor.frame_variant)
        if sprite is None:
            return None
        bbox = sprite.getbbox()
        if bbox is None:
            return None
        left, top, right, bottom = bbox
        return left, top, right, bottom

    def _apply_enemy_contact(self) -> None:
        """Touching an active enemy costs one energy segment (AEPROG 0x4472
        change_energy(-1)).  No damage during the hurt window, immortality, or
        god mode.  Energy 0 is death.

        The overlap uses the original per-sprite hitboxes (AEPROG 0x4bfd): the
        hand-tuned player face box (DS:0x79E) against the actor's sprite bounds,
        not the whole 32x40/16x16 sprites - otherwise enemies hit from too far.
        """
        if self._hurt_cooldown > 0 or self._invuln_timer > 0:
            return
        if self.god_mode:
            return
        st = self.player.state
        pxn, pyn, pxf, pyf = player_face_box(self._player_face_boxes, st.frame, st.facing)
        p_left, p_right = st.x + pxn, st.x + pxf
        p_top, p_bottom = st.y + pyn, st.y + pyf
        for actor in self.simulation.actors.values():
            if actor.room_index != self.room_index:
                continue
            if not getattr(actor, "active", True) or getattr(actor, "hidden", 0):
                continue
            box = self._actor_face_box(actor)
            if box is None:
                continue
            axn, ayn, axf, ayf = box
            a_left, a_right = actor.x + axn, actor.x + axf
            a_top, a_bottom = actor.y + ayn, actor.y + ayf
            if p_left <= a_right and a_left <= p_right and p_top <= a_bottom and a_top <= p_bottom:
                self._hurt_player()
                return

    def _hurt_player(self) -> None:
        self._hurt_cooldown = HURT_INVULN_TICKS
        self.player.state.energy -= 1
        self.player.pending_sounds.append(SFX_HURT)
        if self.player.state.energy <= 0:
            self._on_player_death()

    def _drain_sounds(self) -> None:
        """Play the SFX queued by the player controller and the actor VM."""
        ids = list(self.player.pending_sounds)
        self.player.pending_sounds.clear()
        ids.extend(self.simulation.drain_pending_sound_ids())
        for sound_id in ids:
            self.audio.play_sfx(sound_id)

    def _on_player_death(self) -> None:
        # AEPROG 0x3986 restarts the level after the death animation; without a
        # lives counter we simply reload the level at full energy.
        self._load(self.level, self.part_index)

    def _try_start_exit_door(self) -> bool:
        if not self.artifact_puzzle_solved:
            return False
        door = header_exit_door(self.simulation.part.header)
        if door is None or door.room_index != self.room_index:
            return False
        if not player_aligned_with_exit_door(self.player.state, door):
            return False
        next_level_index = self.level.index + 1
        if next_level_index >= len(self.project.levels):
            return False
        self._exit_enter_ticks = EXIT_ANIMATION_STEPS
        self._exit_door_frame = EXIT_OPEN_DOOR_FRAMES[0]
        self._exit_player_start_frame = self.player.state.frame
        self._exit_player_hidden = False
        # The enter phase walks the player into the doorway (AEPROG draws it at
        # the door x and door y + 4).
        self._exit_door_x = door.x_raw * 2
        self._exit_door_y = door.y_raw + 4
        self._exit_target_level_index = next_level_index
        self._last_tick_time = time.perf_counter()
        self._current_render_snapshot = self._capture_render_snapshot()
        if not self.interpolate_frames:
            self._render()
        self.root.after(self._tick_ms, self._tick)
        return True

    def _try_start_artifact_puzzle(self) -> bool:
        if self.artifact_puzzle_solved or self.artifact_puzzle is not None:
            return False
        if not self._all_artifacts_collected():
            return False
        self._artifact_complete_ticks = len(ARTIFACT_COMPLETE_FRAMES)
        self.player.state.frame = ARTIFACT_COMPLETE_FRAMES[0]
        self._last_tick_time = time.perf_counter()
        self._current_render_snapshot = self._capture_render_snapshot()
        if not self.interpolate_frames:
            self._render()
        self.root.after(self._tick_ms, self._tick)
        return True

    def _tick_artifact_complete_animation(self) -> bool:
        if self._artifact_complete_ticks <= 0:
            return False
        frame_index = len(ARTIFACT_COMPLETE_FRAMES) - self._artifact_complete_ticks
        self.player.state.frame = ARTIFACT_COMPLETE_FRAMES[min(frame_index, len(ARTIFACT_COMPLETE_FRAMES) - 1)]
        self._artifact_complete_ticks -= 1
        if self._artifact_complete_ticks <= 0:
            self.artifact_puzzle = ArtifactPuzzleState(
                level_index=self.level.index,
                expert=self.part_index == 1,
            )
            self._previous_keys = set(self._keys)
            self._render()
            self.root.after(self._tick_ms, self._tick)
            return True
        self._last_tick_time = time.perf_counter()
        self._current_render_snapshot = self._capture_render_snapshot()
        if not self.interpolate_frames:
            self._render()
        self.root.after(self._tick_ms, self._tick)
        return True

    def _tick_artifact_puzzle(self) -> None:
        # Input is handled immediately in _on_key_press (event-driven, no dropped
        # taps); this keeps the main loop alive while the puzzle is on screen.
        if self.artifact_puzzle is None:
            return
        self._previous_keys = set(self._keys)
        self._render()
        self.root.after(self._tick_ms, self._tick)

    def _tick_exit_enter_animation(self) -> bool:
        if self._exit_enter_ticks <= 0:
            return False
        step = EXIT_ANIMATION_STEPS - self._exit_enter_ticks
        door_frame, player_frame = exit_animation_step(step)
        self._exit_door_frame = door_frame
        if player_frame is None:
            # Door-closing phase: the player has entered and is gone.
            self._exit_player_hidden = True
        else:
            self._exit_player_hidden = False
            if player_frame == EXIT_KEEP_PLAYER_FRAME:
                self.player.state.frame = self._exit_player_start_frame
            else:
                self.player.state.frame = player_frame
                self.player.state.x = self._exit_door_x
                self.player.state.y = self._exit_door_y
        self._exit_enter_ticks -= 1
        if self._exit_enter_ticks <= 0 and self._exit_target_level_index is not None:
            self._exit_door_frame = 0
            self._exit_player_hidden = False
            self._start_answer_puzzle_crossfade()
            self.root.after(self._tick_ms, self._tick)
            return True
        self._last_tick_time = time.perf_counter()
        self._current_render_snapshot = self._capture_render_snapshot()
        if not self.interpolate_frames:
            self._render()
        self.root.after(self._tick_ms, self._tick)
        return True

    def _start_answer_puzzle(self) -> None:
        self.answer_puzzle, self.answer_player = self._prepare_answer_puzzle_state()
        self._answer_exit_ticks = 0
        self._answer_player_hidden = False
        self._previous_keys = set(self._keys)
        self.root.focus_force()
        self._render()

    def _start_answer_puzzle_crossfade(self) -> None:
        source = self._render_current_game_image()
        puzzle, controller = self._prepare_answer_puzzle_state()
        target = self._render_answer_puzzle_image_for(puzzle, show_player=True)

        def finish() -> None:
            self._crossfade_source = None
            self._crossfade_target = None
            self._crossfade_finish = None
            self.scene = "game"
            self.answer_puzzle = puzzle
            self.answer_player = controller
            self._answer_exit_ticks = 0
            self._answer_player_hidden = False
            self._previous_keys = set(self._keys)
            self.root.focus_force()
            self._render()

        self._start_crossfade(source, target, finish)

    def _tick_answer_puzzle(self) -> None:
        puzzle = self.answer_puzzle
        controller = self.answer_player
        if puzzle is None or controller is None:
            return
        if self._answer_exit_ticks > 0:
            self._tick_answer_exit_animation()
            return

        command = PlayerInput(
            left="left" in self._keys,
            right="right" in self._keys,
            jump="up" in self._keys,
            down="down" in self._keys,
            change_tool=False,
            use_tool=False,
        )
        started_exit = False
        if command.jump:
            for door_index, door_y in enumerate((18, 66, 114)):
                door = HeaderExitDoor(room_index=0, x_raw=122, y_raw=door_y)
                if player_aligned_with_exit_door(puzzle.player, door):
                    if puzzle.choose(door_index):
                        self._answer_exit_ticks = EXIT_ANIMATION_STEPS
                        self._exit_player_start_frame = puzzle.player.frame
                        self._exit_door_x = door.x_raw * 2
                        self._exit_door_y = door.y_raw + 4
                        self._answer_player_hidden = False
                        started_exit = True
                    break
        if not started_exit:
            controller.tick(command, self.answer_room.tiles)
        self._previous_keys = set(self._keys)
        self._render()
        self.root.after(self._tick_ms, self._tick)

    def _tick_answer_exit_animation(self) -> None:
        puzzle = self.answer_puzzle
        if puzzle is None:
            return
        step = EXIT_ANIMATION_STEPS - self._answer_exit_ticks
        door_frame, player_frame = exit_animation_step(step)
        puzzle.door_frame = door_frame
        if player_frame is None:
            self._answer_player_hidden = True
        else:
            self._answer_player_hidden = False
            if player_frame == EXIT_KEEP_PLAYER_FRAME:
                puzzle.player.frame = self._exit_player_start_frame
            else:
                puzzle.player.frame = player_frame
                puzzle.player.x = self._exit_door_x
                puzzle.player.y = self._exit_door_y
        self._answer_exit_ticks -= 1
        if self._answer_exit_ticks <= 0 and self._exit_target_level_index is not None:
            self._start_answer_result_crossfade()
            self.root.after(self._tick_ms, self._tick)
            return
        self._render()
        self.root.after(self._tick_ms, self._tick)

    def _start_answer_result_crossfade(self) -> None:
        if self.answer_puzzle is None or self._exit_target_level_index is None:
            return
        source = self._render_current_answer_puzzle_image()
        completed_after = set(self.completed_levels)
        completed_after.add(self.level.index)

        if self.level.index < ANCIENT_WORLD_LEVEL_INDEX and self.level.index % 4 == 3:
            completed_regions = self._completed_map_regions_for_levels(completed_after)
            if len(completed_regions) == len(MAP_CHOICES) and len(self.project.levels) > ANCIENT_WORLD_LEVEL_INDEX:
                target = self.map_renderer.render_ancient_reveal(0, ANCIENT_REVEAL_FRAMES)

                def finish() -> None:
                    self._crossfade_source = None
                    self._crossfade_target = None
                    self._crossfade_finish = None
                    self.completed_levels = completed_after
                    self.answer_puzzle = None
                    self.answer_player = None
                    self._exit_target_level_index = None
                    self._answer_exit_ticks = 0
                    self.scene = "ancient_reveal"
                    self._ancient_reveal_frame = 0
                    self._reset_render_snapshots()
                    self.root.focus_force()
                    self._render()

                self._start_crossfade(source, target, finish)
                return

            next_selection = self._normalized_map_selection(self.map_selection, completed_regions)
            target = self._map_image(selected=next_selection, completed_regions=completed_regions)

            def finish() -> None:
                self._crossfade_source = None
                self._crossfade_target = None
                self._crossfade_finish = None
                self.completed_levels = completed_after
                self.answer_puzzle = None
                self.answer_player = None
                self._exit_target_level_index = None
                self._answer_exit_ticks = 0
                self.scene = "map"
                self.map_selection = next_selection
                self.audio.play_map_music()
                self._reset_render_snapshots()
                self.root.focus_force()
                self._render()

            self._start_crossfade(source, target, finish)
            return

        next_level_index = self._exit_target_level_index
        target = self._preview_level_start_image(next_level_index)

        def finish() -> None:
            self._crossfade_source = None
            self._crossfade_target = None
            self._crossfade_finish = None
            self.completed_levels = completed_after
            self.answer_puzzle = None
            self.answer_player = None
            self._answer_exit_ticks = 0
            self.scene = "game"
            self._level_var.set(next_level_index)
            self._load(self.project.levels[next_level_index], self.part_index)

        self._start_crossfade(source, target, finish)

    def _hud_state(self) -> GameHudState:
        region_index, cavern_index = hud_indices_for_level(self.level.index)
        return GameHudState(
            tool_index=self.player.state.tool,
            artifact_pieces=len(self.collected_artifacts),
            energy=self.player.state.energy,
            invulnerability_uses=self.immortality_uses,
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

    @staticmethod
    def _is_teleport(a: tuple[int, int], b: tuple[int, int]) -> bool:
        """A jump larger than a few tiles is a reset/respawn (e.g. a projectile
        snapping back to its origin), not real movement, so it must not be
        smoothed."""
        return abs(b[0] - a[0]) > INTERPOLATION_SNAP_DISTANCE or abs(b[1] - a[1]) > INTERPOLATION_SNAP_DISTANCE

    def _interpolation_alpha(self) -> float:
        if not self.interpolate_frames:
            return 1.0
        return max(0.0, min(1.0, (time.perf_counter() - self._last_tick_time) / self._tick_seconds))

    def _interpolated_player_state(self, alpha: float):
        previous = self._previous_render_snapshot
        current = self._current_render_snapshot
        if not self.interpolate_frames or previous is None or current is None or previous.room_index != current.room_index:
            return self.player.state
        old_xy = (previous.player_x, previous.player_y)
        new_xy = (current.player_x, current.player_y)
        if self._is_teleport(old_xy, new_xy):
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
            if old_xy is None or new_xy is None or self._is_teleport(old_xy, new_xy):
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
        if self.scene == "difficulty":
            self._show_image(self.dialog_renderer.render(self.difficulty_selection))
            return
        if self.scene == "map":
            self.map_selection = self._normalized_map_selection(self.map_selection)
            self._show_image(self._map_image(selected=self.map_selection))
            return
        if self.scene == "map_transition":
            self._show_image(
                self.map_renderer.render_level_enter_transition(
                    self.map_selection,
                    self._completed_map_regions(),
                    self._map_transition_frame,
                    MAP_LEVEL_TRANSITION_FRAMES,
                )
            )
            return
        if self.scene == "crossfade":
            if self._crossfade_source is None or self._crossfade_target is None:
                return
            alpha = max(0.0, min(1.0, self._crossfade_frame / max(1, CROSSFADE_FRAMES)))
            self._show_image(Image.blend(self._crossfade_source, self._crossfade_target, alpha))
            return
        if self.scene == "ancient_reveal":
            self._show_image(self.map_renderer.render_ancient_reveal(self._ancient_reveal_frame, ANCIENT_REVEAL_FRAMES))
            return
        if self.artifact_puzzle is not None:
            image = self.puzzle_renderer.render(self.artifact_puzzle)
            self._show_image(image)
            return
        if self.answer_puzzle is not None:
            self._show_image(self._render_current_answer_puzzle_image())
            return
        actors = [
            actor
            for actor in self.simulation.actors.values()
            if actor.room_index == self.room_index
        ]
        alpha = self._interpolation_alpha()
        draw_player = self._interpolated_player_state(alpha)
        draw_actors = self._interpolated_actors(actors, alpha)
        platform_offsets = self._interpolated_platform_offsets(alpha)
        frame_override, blink_off, halo = self._player_draw_state()
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
            apple_collected=self._apple_collected(),
            show_exit_door=self.artifact_puzzle_solved,
            exit_door_frame=self._exit_door_frame,
            show_player=not self._exit_player_hidden and not blink_off,
            player_frame_override=frame_override,
            player_halo=halo,
        )
        self._show_image(image)

    def _player_draw_state(self) -> tuple[int | None, bool, bool]:
        """Resolve the post-hit / immortality draw per AEPROG 0x437c.

        Returns (frame_override, blink_off, halo).  The hurt window takes
        priority over the halo: its first ticks show the hurt frame, the rest
        blink the player on/off; immortality otherwise draws the halo.
        """
        if self._hurt_cooldown > 0:
            if self._hurt_cooldown > HURT_ANIM_THRESHOLD:
                return HURT_FRAME, False, False
            # Blink: AEPROG draws the player only while the timer is odd.
            return None, (self._hurt_cooldown % 2 == 0), False
        if self._invuln_timer > 0:
            return None, False, True
        return None, False, False

    def _show_image(self, image: Image.Image) -> None:
        if self.scale != 1:
            image = image.resize(
                (image.width * self.scale, image.height * self.scale),
                Image.Resampling.NEAREST,
            )
        self._photo = ImageTk.PhotoImage(image)
        self.canvas.create_image(0, 0, image=self._photo, anchor=tk.NW)

    def run(self) -> None:
        self.root.mainloop()
