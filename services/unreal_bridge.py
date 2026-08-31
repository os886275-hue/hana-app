"""Bridge to the running Unreal Editor's Remote Control HTTP API.

Drives UE 5.6's built-in MetaHuman Audio-Driven Animation (Speech2Face) to
turn synthesized TTS audio into facial animation on Hana entirely locally --
no Audio2Face container, no nvidia_ace, no gRPC, no external service at all.

Same HTTP contract used by the ue-mcp bridge (avatar1/ue-mcp/ue_mcp_server.py):
PUT /remote/object/call -> PythonScriptLibrary.ExecutePythonCommandEx.
"""
import os
import requests

UE_HOST = os.getenv("UE_RC_HOST", "127.0.0.1")
UE_PORT = os.getenv("UE_RC_PORT", "30010")
UE_URL = f"http://{UE_HOST}:{UE_PORT}/remote/object/call"
UE_TIMEOUT = float(os.getenv("UE_RC_TIMEOUT", "60"))

PY_LIB = "/Script/PythonScriptPlugin.Default__PythonScriptLibrary"

# Ship mounted under /MetaHuman with the MetaHuman plugin.
AUDIO_ENCODER = ("/MetaHuman/Speech2Face/NNE_AudioDrivenAnimation_AudioEncoder."
                  "NNE_AudioDrivenAnimation_AudioEncoder")
ANIM_DECODER = ("/MetaHuman/Speech2Face/NNE_AudioDrivenAnimation_AnimationDecoder."
                 "NNE_AudioDrivenAnimation_AnimationDecoder")

# Seconds to schedule the exported audio track ahead of the animation track,
# compensating for real audio device/buffer output latency that pose
# evaluation doesn't pay. Started life at 0.08s from a bench test (see
# _SOLVE_AND_PLAY) -- tune by ear: lips still lead -> raise it, lips now
# lag -> lower it.
AUDIO_LATENCY_COMPENSATION = float(os.getenv("UNREAL_AUDIO_LATENCY_COMPENSATION", "0.08"))

_SOLVE_AND_PLAY = '''
import unreal

WAV, NAME, AVATAR, CAPTION = {wav!r}, {name!r}, {avatar!r}, {caption!r}

# Resolve the character Blueprint by asset name, so callers pass "BP_Hana"
# rather than a content path. Sequencer names the spawnable after the
# Blueprint's *display* name (underscores become spaces), while the level's
# own copy keeps the class name -- that difference is how they're told apart.
_ar = unreal.AssetRegistryHelpers.get_asset_registry()
AVATAR_BP = None
for _a in _ar.get_assets_by_path("/Game/MetaHumans", recursive=True):
    if str(_a.asset_name) == AVATAR and str(_a.asset_class_path.asset_name) == "Blueprint":
        AVATAR_BP = unreal.load_object(None, "{{0}}.{{1}}".format(str(_a.package_name), AVATAR))
        break
if AVATAR_BP is None:
    raise SystemExit("No Blueprint named " + AVATAR + " under /Game/MetaHumans")
CLASS_NAME = AVATAR + "_C"

# Both the level's own actor and Sequencer's spawnable share this class, but
# Sequencer names its copy from the Blueprint's *display* name -- "BP_avatar1"
# becomes "BP Avatar 1", capitalised with digits split off, so string-munging
# the asset name does not work. The level actor is always named <Class>_<n>;
# the spawnable never is. That is the reliable discriminator.
def _is_spawnable(a):
    return (a.get_class().get_name() == CLASS_NAME
            and not a.get_name().startswith(CLASS_NAME))

import time as _t
_T0 = _t.time()
_marks = []
def _mark(label):
    _marks.append((label, _t.time() - _T0))

task = unreal.AssetImportTask()
task.filename, task.destination_path, task.destination_name = WAV, "/Game/Audio", NAME
task.automated = task.replace_existing = task.save = True
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
sw = unreal.load_object(None, "/Game/Audio/" + NAME + "." + NAME)
if sw is None:
    raise SystemExit("import failed for " + WAV)

# Decode/prime the sound now, well before playback starts, so the actual
# play call later doesn't pay the first-play decode-latency cost -- that
# latency (absent from animation, which applies on the next tick) is what
# made her lips start moving noticeably before the audio became audible.
unreal.GameplayStatics.prime_sound(sw)
_mark('import+prime')

perf_name = "Perf_" + NAME
perf = unreal.load_object(None, "/Game/Audio/{{0}}.{{0}}".format(perf_name))
if perf is None:
    perf = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        perf_name, "/Game/Audio", unreal.MetaHumanPerformance,
        unreal.MetaHumanPerformanceFactoryNew())

perf.set_editor_property("input_type", unreal.DataInputType.AUDIO)
perf.set_editor_property("audio", sw)
perf.set_editor_property("downmix_channels", True)
models = perf.get_editor_property("audio_driven_animation_models")
models.set_editor_property("audio_encoder", unreal.SoftObjectPath({enc!r}))
models.set_editor_property("animation_decoder", unreal.SoftObjectPath({dec!r}))
perf.set_editor_property("audio_driven_animation_models", models)
perf.set_editor_property("audio_driven_animation_output_controls",
                         unreal.AudioDrivenAnimationOutputControls.FULL_FACE)

_mark('perf setup')
perf.set_blocking_processing(True)
perf.start_pipeline()
_mark('SOLVE')
if not perf.can_export_animation():
    raise SystemExit("solve produced no animation (frames=" + str(perf.get_number_of_processed_frames()) + ")")

ed = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ed.get_game_world()
if world is None:
    raise SystemExit("Editor is not in Play mode -- press Play first (Level Sequence "
                      "spawnables only materialize at runtime).")

# Hide the level's own static Hana -- only the sequence-spawned, animated
# copy should be visible. Idempotent: harmless to redo every call.
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
    if a.get_class().get_name() == CLASS_NAME and not _is_spawnable(a):
        a.set_actor_hidden_in_game(True)

# Clean up whatever the previous turn spawned before playing this one --
# otherwise every turn leaves behind another LevelSequenceActor + spawned
# Hana copy, accumulating duplicates in the scene.
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.LevelSequenceActor):
    a.destroy_actor()
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
    if _is_spawnable(a):
        a.destroy_actor()

ls = unreal.MetaHumanPerformanceExportUtils.get_export_level_sequence_settings(perf)
ls.set_editor_property("show_export_dialog", False)
ls.set_editor_property("package_path", "/Game/Audio")
ls.set_editor_property("asset_name", "LS_" + NAME)
ls.set_editor_property("target_meta_human_class", AVATAR_BP)
ls.set_editor_property("export_audio_track", True)
ls.set_editor_property("export_control_rig_track", True)
ls.set_editor_property("enable_meta_human_head_movement", True)
ls.set_editor_property("enable_control_rig_head_movement", True)
for off in ("export_camera", "export_identity", "export_video_track",
            "export_depth_track", "export_image_plane", "export_transform_track"):
    ls.set_editor_property(off, False)
seq = unreal.MetaHumanPerformanceExportUtils.export_level_sequence(perf, ls)
_mark('export sequence')
if seq is None:
    raise SystemExit("export_level_sequence returned None")

# The Speech2Face solve quantizes to whole animation frames (30fps here), so
# the exported Control Rig sections are consistently ~1 frame short of the
# audio's real length -- and export leaves them with no explicit end bound,
# so they simply stop evaluating the instant they run out of keyframes while
# the (longer) audio track keeps playing. Bound them out to the sequence's
# own playback end so they hold their last pose instead of visibly freezing
# before the line finishes.
_playback_end = seq.get_playback_end_seconds()
for _b in seq.get_bindings():
    for _t in _b.get_tracks():
        if _t.get_class().get_name() in ("MovieSceneControlRigParameterTrack",
                                         "MovieScene3DTransformTrack"):
            for _s in _t.get_sections():
                try:
                    _s.set_end_frame_seconds(_playback_end)
                except Exception:
                    pass

# prime_sound (above) hides the first-play decode cost, but real audio
# output still has device/buffer latency the animation track doesn't pay --
# pose evaluation applies the instant the playhead moves, audible sound
# lags a beat behind. Give the audio section a head start on the timeline
# so what's actually audible lines up with the lip movement instead of
# trailing it. 80ms is a starting calibration, not a measured constant --
# retune AUDIO_LATENCY_COMPENSATION below if lips still lead or now lag.
_LATENCY = {latency!r}
for _t in seq.get_tracks():
    if _t.get_class().get_name() == "MovieSceneAudioTrack":
        for _s in _t.get_sections():
            _s.set_start_frame_seconds(_s.get_start_frame_seconds() - _LATENCY)
seq.set_playback_start_seconds(seq.get_playback_start_seconds() - _LATENCY)

settings = unreal.MovieSceneSequencePlaybackSettings()
# Without this, Sequencer destroys the spawned Hana and reverts everything
# the instant the clip finishes playing -- she'd vanish moments after each
# line ends instead of staying visible in her final pose.
settings.set_editor_property("finish_completion_state_override",
                             unreal.MovieSceneCompletionModeOverride.FORCE_KEEP_STATE)
settings.set_editor_property("pause_at_end", True)
player, seq_actor = unreal.LevelSequencePlayer.create_level_sequence_player(world, seq, settings)
# Force one evaluation at frame 0 so Sequencer materializes the spawnable
# Hana *before* playback starts. Without this she only appears on the first
# real engine tick, so the camera-positioning pass below has to poll for her
# while the audio is already running -- which is what made the sound seem to
# start over a second before she did. It also means the TRASH_ duplicate
# components stay visible until that pass lands.
try:
    _pp = unreal.MovieSceneSequencePlaybackParams()
    _pp.set_editor_property("position_type", unreal.MovieScenePositionType.TIME)
    _pp.set_editor_property("time", 0.0)
    _pp.set_editor_property("update_method", unreal.UpdatePositionMethod.JUMP)
    player.set_playback_position(_pp)
except Exception as _e:
    print("prespawn jump failed (harmless): " + str(_e))
player.play()

if CAPTION:
    _dur = float(sw.get_editor_property("duration")) or 5.0
    # key=0 replaces the previous caption instead of stacking lines up.
    unreal.SystemLibrary.print_string(
        world, CAPTION, True, False,
        unreal.LinearColor(1.0, 0.95, 0.2, 1.0), _dur, "caption")

_mark('play')
_prev = 0.0
for _lbl, _el in _marks:
    print("  TIMING %-18s %6.2fs  (+%.2fs)" % (_lbl, _el, _el - _prev))
    _prev = _el
print("PLAYED=" + seq.get_path_name())
'''

# The sequence's spawnable Hana only materializes once the engine actually
# ticks and evaluates the sequence -- which can't happen inside the single
# blocking ExecutePythonCommandEx call above. This runs as a second,
# separate call a moment later, once the spawned actor genuinely exists, to
# point the camera at her (she doesn't spawn in the same place/orientation
# as the original static actor).
_POSITION_CAMERA = '''
import unreal

AVATAR = {avatar!r}
CLASS_NAME = AVATAR + "_C"

ed = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ed.get_game_world()
if world is None:
    raise SystemExit("not in PIE")

# See _is_spawnable in the solve snippet: the level actor is named <Class>_<n>,
# Sequencer's spawnable is named from the Blueprint display name instead.
spawned = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
           if a.get_class().get_name() == CLASS_NAME
           and not a.get_name().startswith(CLASS_NAME)]
if not spawned:
    raise SystemExit("spawnable did not appear yet for " + AVATAR)
hana = spawned[0]

# The spawnable's construction script runs twice, leaving a duplicate,
# unposed (no leader_pose_component) copy of every mesh renamed to
# TRASH_SkeletalMeshComponent_N -- still visible. The rigid ones (shoes,
# pants, body, face) just sit in a static bind pose unnoticed underneath
# the real ones, but the duplicate sweater is cloth-simulated with no
# skeletal anchor at all, so it flies off into the huge wing-shaped mess.
for c in hana.get_components_by_class(unreal.SkeletalMeshComponent):
    if c.get_name().startswith("TRASH_"):
        c.set_hidden_in_game(True)
        c.set_visibility(False)

face = [c for c in hana.get_components_by_class(unreal.SkeletalMeshComponent)
        if c.get_name() == "Face"][0]
head = face.get_socket_location("head")

# She renders facing -X regardless of what get_actor_forward_vector() reports,
# because the mesh is rotated inside the Blueprint. Sit on -X looking back.
pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
pc = unreal.GameplayStatics.get_player_controller(world, 0)
rot = unreal.Rotator(0.0, 0.0, 0.0)
pawn.set_actor_location(unreal.Vector(head.x - 38.0, head.y, head.z + 1.0), False, False)
pawn.set_actor_rotation(rot, False)
pc.set_control_rotation(rot)
print("CAMERA_SET")
'''


def _post(payload):
    resp = requests.put(UE_URL, json=payload, timeout=UE_TIMEOUT)
    resp.raise_for_status()
    return resp.json() if resp.text.strip() else {}


def exec_python(code):
    """Run Python inside the editor. Returns (ok, result, log_text)."""
    resp = _post({
        "objectPath": PY_LIB,
        "functionName": "ExecutePythonCommandEx",
        "parameters": {
            "PythonCommand": code,
            "ExecutionMode": "ExecuteFile",
            "FileExecutionScope": "Private",
        },
        "generateTransaction": True,
    })
    ok = bool(resp.get("ReturnValue", False))
    result = resp.get("CommandResult") or ""
    log_lines = []
    for entry in resp.get("LogOutput") or []:
        text = entry.get("Output", "")
        kind = entry.get("Type", "Info")
        log_lines.append(text if kind == "Info" else f"[{kind}] {text}")
    return ok, result, "".join(log_lines).rstrip()


_CAPTION_FRAME = '''
import unreal
_ed = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
_w = _ed.get_game_world()
if _w is not None:
    unreal.SystemLibrary.print_string(_w, {full!r}, True, False,
        unreal.LinearColor(0.80, 0.80, 0.80, 1.0), {dur}, "cap_full")
    unreal.SystemLibrary.print_string(_w, {word!r}, True, False,
        unreal.LinearColor(0.15, 1.0, 0.35, 1.0), {dur}, "cap_word")
'''


def _stream_caption(t0, timings, full_text):
    """Push one caption frame per word, timed against playback start.

    Driven from here rather than from an in-editor tick callback: a leaked
    Slate tick handler would keep firing in the user's editor long after this
    process exits. One HTTP round-trip per word is ~50ms, comfortably inside
    a spoken word.
    """
    import time
    for word, start, end in timings:
        wait = t0 + start - time.time()
        if wait > 0:
            time.sleep(wait)
        elif end < time.time() - t0:
            continue                      # already spoken; do not lag behind
        hold = max(end - start, 0.25) + 0.05
        try:
            exec_python(_CAPTION_FRAME.format(full=full_text, word=word, dur=hold))
        except Exception:
            return                        # editor went away mid-line; not fatal


def animate_hana_from_wav(wav_path: str, name: str = "LiveTTS",
                          avatar: str = "BP_Hana", caption: str = "",
                          timings=None) -> bool:
    """Solve TTS audio into MetaHuman facial animation and play it on Hana.

    Runs entirely locally inside the Unreal editor (UE 5.6's built-in
    audio-driven animation) -- no Audio2Face container, no nvidia_ace, no gRPC.
    Never raises: a hiccup here shouldn't take down the voice pipeline.

    Uses a fresh, timestamped asset name each call rather than reusing one:
    Hana's Face component keeps a live reference to whichever AnimSequence is
    currently playing, so re-exporting over that exact same asset on the next
    turn fails (export_animation_sequence silently returns None even though
    the solve itself succeeded). This does mean /Game/Audio accumulates one
    SoundWave/Performance/AnimSequence set per turn over a long session --
    fine for now, worth a periodic manual cleanup for long-running sessions.
    """
    import time
    unique_name = f"{name}_{int(time.time() * 1000)}"

    code = _SOLVE_AND_PLAY.format(wav=wav_path, name=unique_name, avatar=avatar,
                                  caption="" if timings else (caption or ""),
                                  enc=AUDIO_ENCODER, dec=ANIM_DECODER,
                                  latency=AUDIO_LATENCY_COMPENSATION)
    try:
        ok, result, log = exec_python(code)
    except Exception as e:
        print(f"[UnrealBridge] Could not reach the Unreal editor: {e}")
        return False
    if not ok:
        print(f"[UnrealBridge] Solve/play failed:\n{log or result}")
        return False
    print(f"[UnrealBridge] {log or result}")

    cap_thread = None
    if timings:
        import threading
        t0 = time.time()
        cap_thread = threading.Thread(target=_stream_caption,
                                      args=(t0, timings, caption or ""))
        cap_thread.start()

    # Second round-trip, after giving the engine a moment to actually tick
    # and spawn the sequence's Hana, to point the camera at her.
    # Poll fast and often rather than slow and few: at 0.3s x 5 this could take
    # a full 1.5s to land, all of it with the audio already playing and the
    # camera still pointing somewhere else.
    for attempt in range(30):
        time.sleep(0.05)
        try:
            cam_ok, cam_result, cam_log = exec_python(_POSITION_CAMERA.format(avatar=avatar))
        except Exception as e:
            print(f"[UnrealBridge] Camera positioning: could not reach the editor: {e}")
            break
        if cam_ok:
            print(f"[UnrealBridge] {cam_log or cam_result}")
            break
        if attempt == 29:
            print(f"[UnrealBridge] Camera positioning failed after retries:\n{cam_log or cam_result}")

    return True
