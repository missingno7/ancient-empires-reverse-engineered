"""Tk presentation shell for the reverse-engineered game."""
from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageTk

from ancient_empires.constants import ACTOR_TICK_HZ
from ancient_empires.engine import (
    PlayerController,
    PlayerInput,
    RoomSimulation,
    resolve_room_edge,
)
from ancient_empires.game_data.room_payload import transition_links_for_room
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.rendering.game_screen import GameHudState, GameScreenRenderer


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
        self.show_invisible = False
        self._keys: set[str] = set()
        self._tick_ms = round(1000 / ACTOR_TICK_HZ)
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
        self._render()
        self.root.after(self._tick_ms, self._tick)

    def _build_menu(self) -> None:
        """Native dropdown 'Develop' menu for debugging (level jump, etc.)."""
        menubar = tk.Menu(self.root)
        develop = tk.Menu(menubar, tearoff=0)

        levels = tk.Menu(develop, tearoff=0)
        self._level_var = tk.IntVar(value=self.level.index)
        for i, level in enumerate(self.project.levels):
            levels.add_radiobutton(
                label=f"{i}: {getattr(level, 'name', None) or f'Level {i}'}",
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
        # Placeholders for upcoming cheats (god mode, etc.).
        menubar.add_cascade(label="Develop", menu=develop)
        self.root.config(menu=menubar)

    def _toggle_invisible(self) -> None:
        self.show_invisible = bool(self._show_invisible_var.get())
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
        self.root.focus_force()
        self._render()

    def _on_key_press(self, event: tk.Event) -> None:
        self._keys.add(str(event.keysym).lower())

    def _on_key_release(self, event: tk.Event) -> None:
        self._keys.discard(str(event.keysym).lower())

    def _tick(self) -> None:
        command = PlayerInput(
            left="left" in self._keys,
            right="right" in self._keys,
            jump="up" in self._keys,
            down="down" in self._keys,
            change_tool="return" in self._keys,
            use_tool="space" in self._keys,
        )
        self.player.tick(command, self.simulation.runtime_tiles())
        self._apply_room_transitions()
        self.simulation.set_player_position(self.player.state.x, self.player.state.y)
        # Walk-onto-button activation (0x3c50) plus the actor VM's scripted
        # triggers (opcode 0x08) inside step() are the real control paths.
        self.simulation.apply_player_object_interaction()
        self.simulation.step()
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

    def _render(self) -> None:
        actors = [
            actor
            for actor in self.simulation.actors.values()
            if actor.room_index == self.room_index
        ]
        image = self.screen_renderer.render(
            self.level,
            part_index=self.part_index,
            room_index=self.room_index,
            player=self.player.state,
            actors=actors,
            simulation=self.simulation,
            show_invisible=self.show_invisible,
            hud=GameHudState(tool_index=self.player.state.tool),
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
