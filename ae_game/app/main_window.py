"""Tk presentation shell for the reverse-engineered game."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import copy
import time
import tkinter as tk

from PIL import Image, ImageTk

from ancient_empires.constants import ACTOR_TICK_HZ
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
from ancient_empires.engine.player import TOOL_IMMORTALITY
from ancient_empires.game_data.room_payload import (
    HeaderExitDoor,
    header_exit_door,
    header_object_candidates,
    part_apple_marker,
    apple_marker_screen_xy,
    transition_links_for_room,
)
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.rendering.coordinates import header_object_xy
from ancient_empires.rendering.artifact_puzzle_screen import ArtifactPuzzleScreenRenderer
from ancient_empires.rendering.answer_puzzle_screen import AnswerPuzzleScreenRenderer
from ancient_empires.rendering.game_screen import GameHudState, GameScreenRenderer


REGION_LEVEL_NAMES = ("Near East", "Egypt", "Greece and Rome", "India and China", "Ancient World")
CHAMBER_NUMERALS = ("I", "II", "III", "IV")
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

# Sentinel player-frame returned by exit_animation_step for the opening phase,
# meaning "keep the player's current standing frame".
EXIT_KEEP_PLAYER_FRAME = -1

# Frame-interpolation guard: a per-axis jump larger than this (pixels) between
# two simulation ticks is treated as a teleport/reset (e.g. a projectile
# snapping back to its spawn) and is drawn instantly rather than smoothed.
INTERPOLATION_SNAP_DISTANCE = 48

# Player health (AEPROG DS:0xb82): five bar segments, starts full.
ENERGY_MAX = 4
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


def hud_indices_for_level(level_index: int) -> tuple[int, int]:
    level_index = max(0, int(level_index))
    return min(4, level_index // 4), min(3, level_index % 4)


def level_display_name(level_index: int) -> str:
    region_index, cavern_index = hud_indices_for_level(level_index)
    return f"{REGION_LEVEL_NAMES[region_index]} {CHAMBER_NUMERALS[cavern_index]}"


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
        self.screen_renderer = GameScreenRenderer(project.graphics, project.renderer)
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
        # Placeholders for upcoming cheats (god mode, etc.).
        menubar.add_cascade(label="Develop", menu=develop)
        self.root.config(menu=menubar)

    def _toggle_invisible(self) -> None:
        self.show_invisible = bool(self._show_invisible_var.get())
        self._render()

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

    def _on_key_press(self, event: tk.Event) -> None:
        self._keys.add(str(event.keysym).lower())

    def _on_key_release(self, event: tk.Event) -> None:
        self._keys.discard(str(event.keysym).lower())

    def _tick(self) -> None:
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
        if command.use_tool and self.player.state.tool == TOOL_IMMORTALITY:
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
            self.simulation.fire_laser(
                self.player.state.x, self.player.state.y, self.player.state.facing
            )
        self.simulation.step()
        self._collect_apple()
        self._apply_enemy_contact()
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
        left, top = apple_marker_screen_xy(marker)
        if self._player_overlaps(left, top, 16, 16, self.player.state):
            self.collected_apples.add(self.room_index)
            self.player.state.energy = ENERGY_MAX

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
        if self._invuln_timer > 0 or self.immortality_uses <= 0:
            return
        self.immortality_uses -= 1
        self._invuln_timer = IMMORTALITY_TICKS

    def _apply_enemy_contact(self) -> None:
        """Touching an active enemy costs one energy segment (AEPROG 0x4472
        change_energy(-1)).  No damage during the hurt window, immortality, or
        god mode.  Energy 0 is death."""
        if self._hurt_cooldown > 0 or self._invuln_timer > 0:
            return
        if self.god_mode:
            return
        for actor in self.simulation.actors.values():
            if actor.room_index != self.room_index:
                continue
            if not getattr(actor, "active", True) or getattr(actor, "hidden", 0):
                continue
            # actor.x/y share the player's world space (same model the laser
            # freeze uses); the 16x16 actor box vs the player collision box.
            if self._player_overlaps(actor.x, actor.y, 16, 16, self.player.state):
                self._hurt_player()
                return

    def _hurt_player(self) -> None:
        self._hurt_cooldown = HURT_INVULN_TICKS
        self.player.state.energy -= 1
        if self.player.state.energy <= 0:
            self._on_player_death()

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
        puzzle = self.artifact_puzzle
        if puzzle is None:
            return
        pressed = self._keys - self._previous_keys
        if "left" in pressed:
            puzzle.move_cursor(0, -1)
        if "right" in pressed:
            puzzle.move_cursor(0, 1)
        if "up" in pressed:
            puzzle.move_cursor(-1, 0)
        if "down" in pressed:
            puzzle.move_cursor(1, 0)
        if "f" in pressed:
            puzzle.flip_held_piece()
        if "return" in pressed:
            puzzle.take_or_drop()
        if puzzle.solved:
            self.artifact_puzzle_solved = True
            self.artifact_puzzle = None
            self._reset_render_snapshots()
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
            self._start_answer_puzzle()
            self.root.after(self._tick_ms, self._tick)
            return True
        self._last_tick_time = time.perf_counter()
        self._current_render_snapshot = self._capture_render_snapshot()
        if not self.interpolate_frames:
            self._render()
        self.root.after(self._tick_ms, self._tick)
        return True

    def _start_answer_puzzle(self) -> None:
        self.answer_puzzle = AnswerPuzzleState(
            self.project.exe,
            level_index=self.level.index,
            expert=self.part_index == 1,
            theme=self.level.part(self.part_index).theme,
        )
        start_x, start_y = answer_room_player_start(self.project.ae001[20].decoded)
        self.answer_puzzle.player.x = start_x
        self.answer_puzzle.player.y = start_y
        self.answer_player = PlayerController(self.level, self.part_index, 0)
        self.answer_player.state = self.answer_puzzle.player
        self._answer_exit_ticks = 0
        self._answer_player_hidden = False
        self._previous_keys = set(self._keys)
        self.root.focus_force()
        self._render()

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
            next_level_index = self._exit_target_level_index
            self._exit_target_level_index = None
            self.answer_puzzle = None
            self.answer_player = None
            self._level_var.set(next_level_index)
            self._load(self.project.levels[next_level_index], self.part_index)
            self.root.after(self._tick_ms, self._tick)
            return
        self._render()
        self.root.after(self._tick_ms, self._tick)

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
        if self.artifact_puzzle is not None:
            image = self.puzzle_renderer.render(self.artifact_puzzle)
            self._show_image(image)
            return
        if self.answer_puzzle is not None:
            image = self.answer_puzzle_renderer.render(
                self.answer_puzzle,
                level=self.level,
                part_index=self.part_index,
                hud=self._hud_state(),
                show_player=not self._answer_player_hidden,
            )
            self._show_image(image)
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
