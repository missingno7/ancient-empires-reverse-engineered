"""Optional pygame + ModernGL enhanced lighting pass for the game runtime.

The main game UI is still Tk/ImageTk, but the enhanced playfield effects now use
an off-screen GPU pipeline:

- the classic renderer still produces the base 320x200 frame
- only the playfield crop is processed; HUD is intentionally excluded
- pygame creates a tiny hidden OpenGL context
- ModernGL renders the enhanced playfield into an off-screen framebuffer
- the result is read back into PIL and composited back into the Tk image

This is still a hybrid presentation path because Tk owns the window.  However,
it moves the expensive lighting/shadow math from Pillow/CPU to a GPU fragment
shader and keeps the terrain-occluder merge/caching logic as a separate
refactor-friendly stage.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Iterable, Literal
import array

from PIL import Image

import moderngl
import pygame

from ..constants import CELL_SIZE, ROOM_COLUMNS, ROOM_ROWS
from ..engine.runtime import platform_xy
from ..game_data.level_format import Level, Room
from ..game_data.room_payload import header_object_candidates, parse_platform_triplets
from .coordinates import header_object_xy
from .game_screen import HUD_ORIGIN, ROOM_ORIGIN, SCREEN_WIDTH


LightKind = Literal["player", "artifact"]
BlockerKind = Literal["terrain", "platform"]
MAX_BLOCKERS = 128
MAX_ARTIFACT_LIGHTS = 16


@dataclass(frozen=True)
class EnhancedRenderConfig:
    """Tweakable visual-only settings for the enhanced renderer."""

    enabled: bool = False

    ambient_enabled: bool = True
    shadows_enabled: bool = True
    terrain_shadows_enabled: bool = True
    platform_shadows_enabled: bool = True
    drop_shadows_enabled: bool = True
    glow_enabled: bool = True

    # GPU internal resolution scale for the enhanced pass. The source image is
    # still the upscaled nearest-neighbor game frame; only the enhanced shader
    # output is rendered at this scale and then upscaled back.
    effect_scale: float = 1.00

    ambient_darkness: float = 0.49
    player_radius: float = 85.0
    player_intensity: float = 1.59
    artifact_radius: float = 50.0
    artifact_intensity: float = 1.15
    glow_strength: float = 0.16
    shadow_opacity: float = 0.75
    terrain_shadow_opacity: float = 0.75
    drop_shadow_opacity: float = 0.27
    shadow_blur: float = 10.0  # kept for UI compatibility; shader softness knob

    def with_updates(self, **kwargs) -> "EnhancedRenderConfig":
        return replace(self, **kwargs)


@dataclass(frozen=True)
class LightEmitter:
    x: float
    y: float
    radius: float
    intensity: float
    color: tuple[int, int, int]
    kind: LightKind


@dataclass(frozen=True)
class Blocker:
    x: int
    y: int
    w: int
    h: int
    kind: BlockerKind


@dataclass(frozen=True)
class EnhancedRenderContext:
    lights: tuple[LightEmitter, ...]
    blockers: tuple[Blocker, ...]


@dataclass(frozen=True)
class _LocalContext:
    player_light: LightEmitter | None
    artifact_lights: tuple[LightEmitter, ...]
    blockers: tuple[Blocker, ...]


VERTEX_SHADER = """
#version 330

in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;

void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""


FRAGMENT_SHADER = f"""
#version 330

#define MAX_BLOCKERS {MAX_BLOCKERS}
#define MAX_ARTIFACT_LIGHTS {MAX_ARTIFACT_LIGHTS}

uniform sampler2D u_base_texture;
uniform vec2 u_output_size;

uniform vec4 u_blockers[MAX_BLOCKERS];
uniform int u_blocker_count;

uniform vec4 u_player_light; // x,y,radius,intensity. intensity<=0 => disabled
uniform vec4 u_artifact_lights[MAX_ARTIFACT_LIGHTS];
uniform int u_artifact_light_count;

uniform int u_projected_shadows;
uniform int u_drop_shadows;
uniform int u_ambient;
uniform int u_glow;

uniform float u_ambient_darkness;
uniform float u_shadow_opacity;
uniform float u_terrain_shadow_opacity;
uniform float u_drop_shadow_opacity;
uniform float u_shadow_softness;
uniform float u_glow_strength;

in vec2 v_uv;
out vec4 fragColor;

float inside_rect(vec2 p, vec4 r) {{
    vec2 q1 = step(r.xy, p);
    vec2 q2 = step(p, r.xy + r.zw);
    return q1.x * q1.y * q2.x * q2.y;
}}

float sd_box(vec2 p, vec2 center, vec2 half_size) {{
    vec2 q = abs(p - center) - half_size;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
}}

bool ray_segment_hits_rect(vec2 ro, vec2 p, vec4 r) {{
    vec2 rd = p - ro;
    vec2 inv = 1.0 / max(abs(rd), vec2(0.0001));
    inv *= sign(rd);

    vec2 bmin = r.xy;
    vec2 bmax = r.xy + r.zw;

    vec2 t0 = (bmin - ro) * inv;
    vec2 t1 = (bmax - ro) * inv;

    vec2 near_t = min(t0, t1);
    vec2 far_t = max(t0, t1);

    float t_near = max(near_t.x, near_t.y);
    float t_far = min(far_t.x, far_t.y);

    return t_far >= max(t_near, 0.0) && t_near < 1.0;
}}

float projected_shadow(vec2 p) {{
    if (u_player_light.w <= 0.0) {{
        return 0.0;
    }}

    float shadow = 0.0;
    vec2 light_pos = u_player_light.xy;
    for (int i = 0; i < MAX_BLOCKERS; ++i) {{
        if (i >= u_blocker_count) break;
        vec4 r = u_blockers[i];
        if (inside_rect(p, r) > 0.5) continue;
        if (ray_segment_hits_rect(light_pos, p, r)) {{
            float fade = smoothstep(250.0, 20.0, distance(p, light_pos));
            shadow = max(shadow, u_shadow_opacity * fade);
        }}
    }}
    return shadow;
}}

float soft_box_shadow(vec2 p, vec2 bmin, vec2 bmax, float softness) {{
    vec2 center = (bmin + bmax) * 0.5;
    vec2 half_size = (bmax - bmin) * 0.5;
    float d = sd_box(p, center, half_size);
    return 1.0 - smoothstep(-softness * 0.35, softness, d);
}}

float platform_drop_shadow(vec2 p) {{
    float shadow = 0.0;
    for (int i = 0; i < MAX_BLOCKERS; ++i) {{
        if (i >= u_blocker_count) break;
        vec4 r = u_blockers[i];
        vec2 rmin = r.xy;
        vec2 rmax = r.xy + r.zw;

        float softness1 = max(3.0, u_shadow_softness * 0.90);
        float softness2 = max(5.0, u_shadow_softness * 1.45);
        float softness3 = max(8.0, u_shadow_softness * 2.10);

        float a1 = soft_box_shadow(
            p,
            vec2(rmin.x + 2.0, rmax.y + 2.0),
            vec2(rmax.x + 1.0, rmax.y + 8.0),
            softness1
        ) * 0.18;

        float a2 = soft_box_shadow(
            p,
            vec2(rmin.x + 6.0, rmax.y + 6.0),
            vec2(rmax.x + 7.0, rmax.y + 15.0),
            softness2
        ) * 0.13;

        float a3 = soft_box_shadow(
            p,
            vec2(rmin.x + 12.0, rmax.y + 13.0),
            vec2(rmax.x + 15.0, rmax.y + 24.0),
            softness3
        ) * 0.08;

        shadow = max(shadow, (a1 + a2 + a3) * u_drop_shadow_opacity * 2.2);
    }}
    return clamp(shadow, 0.0, 0.42);
}}

float player_contact_shadow(vec2 p) {{
    if (u_player_light.w <= 0.0) {{
        return 0.0;
    }}
    vec2 center = u_player_light.xy + vec2(0.0, 13.0);
    vec2 radius = vec2(16.0, 5.0);
    vec2 q = (p - center) / radius;
    float d = dot(q, q);
    return (1.0 - smoothstep(0.55, 1.25, d)) * (u_drop_shadow_opacity * 1.4);
}}

float light_contribution(vec2 p, vec4 light) {{
    if (light.w <= 0.0) return 0.0;
    float d = distance(p, light.xy);
    float lit = 1.0 - smoothstep(0.0, light.z, d);
    return lit * light.w;
}}

vec3 apply_ambient(vec3 color, vec2 p) {{
    float lit = 0.0;
    lit = max(lit, light_contribution(p, u_player_light));
    for (int i = 0; i < MAX_ARTIFACT_LIGHTS; ++i) {{
        if (i >= u_artifact_light_count) break;
        lit = max(lit, light_contribution(p, u_artifact_lights[i]));
    }}
    lit = clamp(lit, 0.0, 1.0);
    float darkness = u_ambient_darkness * (1.0 - lit);
    return color * (1.0 - darkness);
}}

vec3 apply_glow(vec3 color, vec2 p) {{
    vec3 glow_color = vec3(0.0);

    if (u_player_light.w > 0.0) {{
        float d = distance(p, u_player_light.xy);
        float outer = 1.0 - smoothstep(6.0, max(8.0, u_player_light.z * 0.55), d);
        float inner = 1.0 - smoothstep(1.0, max(2.0, u_player_light.z * 0.16), d);
        glow_color += vec3(1.0, 0.72, 0.30) * outer * 0.14 * u_player_light.w;
        glow_color += vec3(1.0, 0.82, 0.45) * inner * 0.26 * u_player_light.w;
    }}

    for (int i = 0; i < MAX_ARTIFACT_LIGHTS; ++i) {{
        if (i >= u_artifact_light_count) break;
        vec4 light = u_artifact_lights[i];
        float d = distance(p, light.xy);
        float outer = 1.0 - smoothstep(8.0, max(10.0, light.z * 0.72), d);
        float inner = 1.0 - smoothstep(2.0, max(4.0, light.z * 0.20), d);
        glow_color += vec3(0.90, 0.96, 1.0) * outer * 0.14 * light.w;
        glow_color += vec3(1.0, 1.0, 1.0) * inner * 0.28 * light.w;
    }}

    return color + glow_color * u_glow_strength;
}}

void main() {{
    vec4 base = texture(u_base_texture, v_uv);
    vec2 p = v_uv * u_output_size;

    vec3 color = base.rgb;

    float shadow = 0.0;
    if (u_projected_shadows == 1) {{
        shadow += projected_shadow(p);
    }}
    if (u_drop_shadows == 1) {{
        shadow += platform_drop_shadow(p);
    }}
    shadow += player_contact_shadow(p);
    shadow = clamp(shadow, 0.0, 0.85);
    color *= (1.0 - shadow);

    if (u_ambient == 1) {{
        color = apply_ambient(color, p);
    }}
    if (u_glow == 1) {{
        color = apply_glow(color, p);
    }}

    fragColor = vec4(clamp(color, 0.0, 1.0), base.a);
}}
"""


class EnhancedGamePostProcessor:
    """GPU-backed enhanced pass.

    The class keeps a persistent hidden pygame/OpenGL context and a ModernGL
    program. Each call uploads the playfield crop as a texture, renders the
    enhanced result into an off-screen framebuffer, reads it back to PIL and
    composites it into the original Tk image.
    """

    def __init__(self) -> None:
        self._backend: _ModernGLBackend | None = None

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()
            self._backend = None

    def apply(
        self,
        image: Image.Image,
        context: EnhancedRenderContext,
        config: EnhancedRenderConfig,
        *,
        scale: float,
    ) -> Image.Image:
        if not config.enabled:
            return image
        if image.mode != "RGBA":
            image = image.convert("RGBA")

        playfield_box = _playfield_box(image.size, scale)
        if playfield_box is None:
            return image

        local = _local_context(context, playfield_box, scale, config)
        if local.player_light is None and not local.artifact_lights:
            return image

        left, top, right, bottom = playfield_box
        playfield = image.crop(playfield_box)

        if self._backend is None:
            self._backend = _ModernGLBackend()
        processed = self._backend.render_playfield(playfield, local, config)

        out = image.copy()
        out.alpha_composite(processed, (left, top))
        return out


class _ModernGLBackend:
    def __init__(self) -> None:
        self._initialized = False
        self._ctx: moderngl.Context | None = None
        self._program: moderngl.Program | None = None
        self._vao: moderngl.VertexArray | None = None
        self._vbo: moderngl.Buffer | None = None
        self._ibo: moderngl.Buffer | None = None
        self._base_texture: moderngl.Texture | None = None
        self._fbo: moderngl.Framebuffer | None = None
        self._fbo_size: tuple[int, int] | None = None
        self._texture_size: tuple[int, int] | None = None
        self._init_gl()

    def close(self) -> None:
        for obj in (self._fbo, self._base_texture, self._vao, self._ibo, self._vbo, self._program):
            try:
                if obj is not None:
                    obj.release()
            except Exception:
                pass
        self._fbo = None
        self._base_texture = None
        self._vao = None
        self._ibo = None
        self._vbo = None
        self._program = None
        self._ctx = None
        try:
            if pygame.display.get_init():
                pygame.display.quit()
            if pygame.get_init():
                pygame.quit()
        except Exception:
            pass

    def _init_gl(self) -> None:
        if self._initialized:
            return
        pygame.init()
        pygame.display.init()
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
        flags = pygame.OPENGL | pygame.DOUBLEBUF | getattr(pygame, "HIDDEN", 0)
        pygame.display.set_mode((1, 1), flags)

        self._ctx = moderngl.create_context()
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)

        self._program = self._ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)

        vertices = array.array(
            "f",
            [
                -1.0, -1.0, 0.0, 1.0,
                 1.0, -1.0, 1.0, 1.0,
                -1.0,  1.0, 0.0, 0.0,
                 1.0,  1.0, 1.0, 0.0,
            ],
        )
        indices = array.array("I", [0, 1, 2, 2, 1, 3])
        self._vbo = self._ctx.buffer(vertices.tobytes())
        self._ibo = self._ctx.buffer(indices.tobytes())
        self._vao = self._ctx.vertex_array(
            self._program,
            [(self._vbo, "2f 2f", "in_pos", "in_uv")],
            self._ibo,
        )
        self._program["u_base_texture"].value = 0
        self._initialized = True

    @property
    def ctx(self) -> moderngl.Context:
        assert self._ctx is not None
        return self._ctx

    @property
    def program(self) -> moderngl.Program:
        assert self._program is not None
        return self._program

    @property
    def vao(self) -> moderngl.VertexArray:
        assert self._vao is not None
        return self._vao

    def _set_uniform(self, name: str, value) -> None:
        """Set a shader uniform only when it exists in the linked program.

        OpenGL is allowed to optimize away uniforms that are declared but not
        used by the final shader. ModernGL exposes only active uniforms, so
        indexing such a name raises KeyError. This keeps the renderer robust
        while the shader/config are still evolving.
        """
        if name in self.program:
            self.program[name].value = value

    def _write_uniform_array(self, name: str, data: bytes) -> None:
        """Write a uniform array only when it exists in the linked program."""
        if name in self.program:
            self.program[name].write(data)

    def _ensure_texture(self, size: tuple[int, int]) -> moderngl.Texture:
        if self._base_texture is None or self._texture_size != size:
            if self._base_texture is not None:
                self._base_texture.release()
            self._base_texture = self.ctx.texture(size, 4)
            self._base_texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._base_texture.repeat_x = False
            self._base_texture.repeat_y = False
            self._texture_size = size
        return self._base_texture

    def _ensure_fbo(self, size: tuple[int, int]) -> moderngl.Framebuffer:
        if self._fbo is None or self._fbo_size != size:
            if self._fbo is not None:
                self._fbo.release()
            color = self.ctx.texture(size, 4)
            color.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._fbo = self.ctx.framebuffer(color_attachments=[color])
            self._fbo_size = size
        return self._fbo

    def render_playfield(self, playfield: Image.Image, context: _LocalContext, config: EnhancedRenderConfig) -> Image.Image:
        src_w, src_h = playfield.size
        scale = max(0.25, min(1.0, float(config.effect_scale)))
        target_w = max(1, int(round(src_w * scale)))
        target_h = max(1, int(round(src_h * scale)))

        if playfield.mode != "RGBA":
            playfield = playfield.convert("RGBA")
        if (target_w, target_h) != playfield.size:
            source = playfield.resize((target_w, target_h), Image.Resampling.NEAREST)
        else:
            source = playfield

        texture = self._ensure_texture((target_w, target_h))
        texture.write(source.tobytes("raw", "RGBA"))
        fbo = self._ensure_fbo((target_w, target_h))
        fbo.use()
        self.ctx.viewport = (0, 0, target_w, target_h)
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)

        player = _scale_light(context.player_light, scale)
        artifacts = [_scale_light(light, scale) for light in context.artifact_lights[:MAX_ARTIFACT_LIGHTS]]
        blockers = [_scale_blocker(blocker, scale) for blocker in context.blockers[:MAX_BLOCKERS]]

        rects: list[float] = []
        for blocker in blockers:
            rects.extend([float(blocker.x), float(blocker.y), float(blocker.w), float(blocker.h)])
        while len(rects) < MAX_BLOCKERS * 4:
            rects.extend([0.0, 0.0, 0.0, 0.0])

        art: list[float] = []
        for light in artifacts:
            art.extend([float(light.x), float(light.y), float(light.radius), float(light.intensity)])
        while len(art) < MAX_ARTIFACT_LIGHTS * 4:
            art.extend([0.0, 0.0, 0.0, 0.0])

        player_uniform = (
            float(player.x), float(player.y), float(player.radius), float(player.intensity)
        ) if player is not None else (0.0, 0.0, 0.0, 0.0)

        self._set_uniform("u_output_size", (float(target_w), float(target_h)))
        self._set_uniform("u_blocker_count", len(blockers))
        self._write_uniform_array("u_blockers", array.array("f", rects).tobytes())
        self._set_uniform("u_player_light", player_uniform)
        self._set_uniform("u_artifact_light_count", len(artifacts))
        self._write_uniform_array("u_artifact_lights", array.array("f", art).tobytes())
        self._set_uniform("u_projected_shadows", int(config.shadows_enabled))
        self._set_uniform("u_drop_shadows", int(config.drop_shadows_enabled))
        self._set_uniform("u_ambient", int(config.ambient_enabled))
        self._set_uniform("u_glow", int(config.glow_enabled))
        self._set_uniform("u_ambient_darkness", float(config.ambient_darkness))
        self._set_uniform("u_shadow_opacity", float(config.shadow_opacity))
        self._set_uniform("u_terrain_shadow_opacity", float(config.terrain_shadow_opacity))
        # Use whichever projected shadow opacity is stronger as the generic shader blocker strength.
        self._set_uniform("u_drop_shadow_opacity", float(config.drop_shadow_opacity))
        self._set_uniform("u_shadow_softness", float(max(1.0, config.shadow_blur)))
        self._set_uniform("u_glow_strength", float(config.glow_strength))

        texture.use(location=0)
        self.vao.render()
        raw = fbo.read(components=4, alignment=1)
        out = Image.frombytes("RGBA", (target_w, target_h), raw, "raw", "RGBA", 0, -1)
        if out.size != playfield.size:
            out = out.resize(playfield.size, Image.Resampling.NEAREST)
        return out


def build_enhanced_context(
    level: Level,
    *,
    part_index: int,
    room_index: int,
    player_state,
    collected_artifacts: set[int] | None = None,
    platform_offsets: dict[int, tuple[int, int]] | None = None,
    config: EnhancedRenderConfig | None = None,
) -> EnhancedRenderContext:
    """Build visual-only light/shadow geometry for the current game screen."""
    config = config or EnhancedRenderConfig()
    part = level.part(part_index)
    room = part.rooms[room_index]
    collected_artifacts = collected_artifacts or set()

    blockers = list(_cached_terrain_blockers(room.part_index, room.index, tuple(room.tiles)))
    blockers.extend(_platform_blockers(room, platform_offsets))

    lights: list[LightEmitter] = []
    if player_state is not None:
        # PlayerController coordinates are gameplay anchor coordinates, not the
        # top-left of the drawn sprite. The classic renderer draws the player at
        # roughly (x - 8, y - 16), and the sprite body is about 16x24 px.
        # Put the torch emitter near the visual center of the player instead of
        # at the anchor/top-left-ish point.
        lights.append(
            LightEmitter(
                ROOM_ORIGIN[0] + float(player_state.x),
                ROOM_ORIGIN[1] + float(player_state.y) - 4.0,
                config.player_radius,
                config.player_intensity,
                (255, 174, 78),
                "player",
            )
        )

    for candidate in header_object_candidates(part.header):
        if candidate.index in collected_artifacts:
            continue
        if candidate.room_plus_one != room.index + 1:
            continue
        x, y = header_object_xy(candidate.x_raw, candidate.y_raw)
        lights.append(
            LightEmitter(
                ROOM_ORIGIN[0] + x + 8.0,
                ROOM_ORIGIN[1] + y + 8.0,
                config.artifact_radius,
                config.artifact_intensity,
                (235, 245, 255),
                "artifact",
            )
        )

    return EnhancedRenderContext(tuple(lights), tuple(blockers))


@lru_cache(maxsize=256)
def _cached_terrain_blockers(part_index: int, room_index: int, tiles: tuple[int, ...]) -> tuple[Blocker, ...]:
    del part_index, room_index
    return _merged_terrain_blockers_from_tiles(tiles)


def _merged_terrain_blockers(room: Room) -> tuple[Blocker, ...]:
    return _cached_terrain_blockers(room.part_index, room.index, tuple(room.tiles))


def _merged_terrain_blockers_from_tiles(tiles: tuple[int, ...]) -> tuple[Blocker, ...]:
    """Merge visible solid 8x8 terrain cells into larger rectangles.

    This keeps the renderer from seeing one occluder per tiny terrain tile.
    It is still rectangle-based (not a full polygon mesh), but it already makes
    terrain shadowing dramatically cheaper and is a useful staging refactor.
    """
    row_runs: list[Blocker] = []
    for row in range(ROOM_ROWS):
        start: int | None = None
        for col in range(ROOM_COLUMNS + 1):
            solid = False
            if col < ROOM_COLUMNS:
                code = tiles[row * ROOM_COLUMNS + col]
                solid = 0x01 <= code <= 0x06
            if solid and start is None:
                start = col
            elif not solid and start is not None:
                x = ROOM_ORIGIN[0] + start * CELL_SIZE
                y = ROOM_ORIGIN[1] + row * CELL_SIZE
                w = (col - start) * CELL_SIZE
                row_runs.append(Blocker(x, y, w, CELL_SIZE, "terrain"))
                start = None

    merged: list[Blocker] = []
    for run in row_runs:
        if merged:
            prev = merged[-1]
            if prev.kind == run.kind and prev.x == run.x and prev.w == run.w and prev.y + prev.h == run.y:
                merged[-1] = Blocker(prev.x, prev.y, prev.w, prev.h + run.h, prev.kind)
                continue
        merged.append(run)
    return tuple(merged)


def _platform_blockers(room: Room, offsets: dict[int, tuple[int, int]] | None) -> tuple[Blocker, ...]:
    """Return shadow/light blockers for moving platforms.

    Important: the visible platform sprite is larger than the solid-looking
    platform core.  Using the full sprite rectangle makes lighting look wrong
    around the blue decorative edge.  Treat platforms like merged 8x8 terrain
    cells instead:

    - horizontal platform: 6 cells = 48x8
    - vertical platform:   6 cells = 8x48

    This matches the user's visual expectation that platform shadows should
    behave like terrain tiles, not like the whole 16x/64x decorative sprite.
    """
    out: list[Blocker] = []
    offsets = offsets or {}

    for platform in parse_platform_triplets(room):
        if not platform.visible:
            continue

        x, y = platform_xy(platform)
        dx, dy = offsets.get(platform.index, (0, 0))
        x += dx
        y += dy

        if platform.orientation == "vertical":
            # Visible sprite is roughly 16x48, but the solid/shadow core should
            # be a centered 8x48 column. Fine-tuned 4 px downward to better
            # match the apparent solid core in-game.
            blocker_x = ROOM_ORIGIN[0] + x + 4
            blocker_y = ROOM_ORIGIN[1] + y + 4
            out.append(Blocker(blocker_x, blocker_y, 8, 48, "platform"))
        else:
            # Visible sprite is roughly 64x16, but the solid/shadow core should
            # be a centered 48x8 strip, i.e. 6 terrain-like 8x8 cells.
            # Fine-tuned 4 px left so the shadowing better matches the visible
            # platform body.
            blocker_x = ROOM_ORIGIN[0] + x + 4
            blocker_y = ROOM_ORIGIN[1] + y + 4
            out.append(Blocker(blocker_x, blocker_y, 48, 8, "platform"))

    return tuple(out)


def _playfield_box(size: tuple[int, int], scale: float) -> tuple[int, int, int, int] | None:
    width, height = size
    left = int(round(ROOM_ORIGIN[0] * scale))
    top = int(round(ROOM_ORIGIN[1] * scale))
    right = min(width, int(round(SCREEN_WIDTH * scale)))
    bottom = min(height, int(round(HUD_ORIGIN[1] * scale)))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _local_context(
    context: EnhancedRenderContext,
    playfield_box: tuple[int, int, int, int],
    scale: float,
    config: EnhancedRenderConfig,
) -> _LocalContext:
    crop_left, crop_top, _, _ = playfield_box
    blockers: list[Blocker] = []
    player_light: LightEmitter | None = None
    artifact_lights: list[LightEmitter] = []

    for blocker in context.blockers:
        if blocker.kind == "terrain" and not config.terrain_shadows_enabled:
            continue
        if blocker.kind == "platform" and not config.platform_shadows_enabled:
            continue
        x = int(round(blocker.x * scale - crop_left))
        y = int(round(blocker.y * scale - crop_top))
        w = max(1, int(round(blocker.w * scale)))
        h = max(1, int(round(blocker.h * scale)))
        blockers.append(Blocker(x, y, w, h, blocker.kind))

    for light in context.lights:
        localized = LightEmitter(
            x=light.x * scale - crop_left,
            y=light.y * scale - crop_top,
            radius=light.radius * scale,
            intensity=light.intensity,
            color=light.color,
            kind=light.kind,
        )
        if localized.kind == "player":
            player_light = localized
        else:
            artifact_lights.append(localized)

    return _LocalContext(player_light=player_light, artifact_lights=tuple(artifact_lights), blockers=tuple(blockers))


def _scale_blocker(blocker: Blocker, scale: float) -> Blocker:
    return Blocker(
        x=int(round(blocker.x * scale)),
        y=int(round(blocker.y * scale)),
        w=max(1, int(round(blocker.w * scale))),
        h=max(1, int(round(blocker.h * scale))),
        kind=blocker.kind,
    )


def _scale_light(light: LightEmitter | None, scale: float) -> LightEmitter | None:
    if light is None:
        return None
    return LightEmitter(
        x=light.x * scale,
        y=light.y * scale,
        radius=max(1.0, light.radius * scale),
        intensity=light.intensity,
        color=light.color,
        kind=light.kind,
    )
