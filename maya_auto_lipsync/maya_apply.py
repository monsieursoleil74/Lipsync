# -*- coding: utf-8 -*-
"""Application du plan de lipsync dans la scene Maya (cles, audio, nettoyage)."""
import os

from maya import cmds, mel

from . import core

_FPS = {
    "game": 15.0, "film": 24.0, "pal": 25.0, "ntsc": 30.0, "show": 48.0,
    "palf": 50.0, "ntscf": 60.0, "23.976fps": 23.976, "29.97fps": 29.97,
    "29.97df": 29.97, "47.952fps": 47.952, "59.94fps": 59.94,
}


def scene_fps():
    unit = cmds.currentUnit(q=True, time=True)
    if unit in _FPS:
        return _FPS[unit]
    if unit.endswith("fps"):
        return float(unit[:-3])
    return 24.0


def scene_audio():
    """(chemin, offset) du son du time slider, ou du premier node audio de la scene."""
    node = None
    try:
        slider = mel.eval("$tmp = $gPlayBackSlider")
        node = cmds.timeControl(slider, q=True, sound=True)
    except Exception:
        pass
    if not node:
        nodes = cmds.ls(type="audio")
        node = nodes[0] if nodes else None
    if not node:
        return None, 0.0
    return cmds.getAttr(node + ".filename"), float(cmds.getAttr(node + ".offset"))


def import_audio(path, start_frame):
    """Charge le wav dans le time slider, decale a start_frame."""
    name = os.path.splitext(os.path.basename(path))[0]
    existing = [n for n in cmds.ls(type="audio") if cmds.getAttr(n + ".filename") == path]
    if existing:
        node = existing[0]
        cmds.setAttr(node + ".offset", start_frame)
    else:
        node = cmds.sound(file=path, offset=start_frame, name=name)
    try:
        slider = mel.eval("$tmp = $gPlayBackSlider")
        cmds.timeControl(slider, e=True, sound=node, displaySound=True)
    except Exception:
        pass
    return node


def resolve_controller(short, namespace=None, cache=None):
    """Retrouve un controleur de la scene a partir de son nom court."""
    if cache is not None and short in cache:
        return cache[short]
    found = None
    candidates = []
    if namespace:
        candidates.append("%s:%s" % (namespace.strip(":"), short))
    candidates.append(short)
    for c in candidates:
        if cmds.objExists(c):
            found = c
            break
    if not found:
        hits = cmds.ls("*:" + short, "*:*:" + short, long=False) or []
        if hits:
            found = hits[0]
    if cache is not None:
        cache[short] = found
    return found


def _settable(ctrl, attr):
    plug = "%s.%s" % (ctrl, attr)
    if not cmds.objExists(plug):
        return False
    if cmds.getAttr(plug, lock=True):
        return False
    conn = cmds.listConnections(plug, s=True, d=False) or []
    # une courbe d'anim existante est OK (on la rekeye), une autre connexion non
    for c in conn:
        if not cmds.nodeType(c).startswith("animCurve"):
            return False
    return True


def clear_keys(library, first, last, namespace=None):
    """Supprime les cles des controleurs de la library sur [first, last]."""
    cache = {}
    for short, attrs in library.controllers().items():
        ctrl = resolve_controller(short, namespace, cache)
        if not ctrl:
            continue
        for attr in attrs:
            plug = "%s.%s" % (ctrl, attr)
            if cmds.objExists(plug):
                cmds.cutKey(ctrl, at=attr, time=(first, last), clear=True)


def apply_plan(library, plan, emotion=1.0, emotion_attr=None, namespace=None,
               tangent="auto", clear=True):
    """Pose les cles du plan dans la scene. Renvoie (nb cles, controleurs manquants)."""
    if not plan:
        return 0, []
    cache = {}
    missing = []
    resolved = {}
    for short in library.controllers():
        ctrl = resolve_controller(short, namespace, cache)
        if ctrl:
            resolved[short] = ctrl
        else:
            missing.append(short)

    first = plan[0]["frame"] - 1
    last = plan[-1]["frame"] + 1
    if clear:
        clear_keys(library, first, last, namespace)

    nkeys = 0
    settable_cache = {}
    for key in plan:
        frame = key["frame"]
        e = emotion
        if emotion_attr:
            try:
                e = float(cmds.getAttr(emotion_attr, time=frame))
            except Exception:
                e = emotion
        values = library.blend_values(key["viseme"], key["weight"], e)
        for short, attrs in values.items():
            ctrl = resolved.get(short)
            if not ctrl:
                continue
            for attr, value in attrs.items():
                sk = (ctrl, attr)
                if sk not in settable_cache:
                    settable_cache[sk] = _settable(ctrl, attr)
                if not settable_cache[sk]:
                    continue
                cmds.setKeyframe(ctrl, at=attr, t=frame, v=value)
                nkeys += 1

    # tangentes douces sans overshoot
    for short, ctrl in resolved.items():
        attrs = [a for a in library.controllers()[short] if settable_cache.get((ctrl, a))]
        if attrs:
            try:
                cmds.keyTangent(ctrl, at=attrs, time=(first, last), itt=tangent, ott=tangent)
            except Exception:
                pass
    return nkeys, missing


def run(audio=None, happy_folder=None, sad_folder=None, rhubarb_exe=None,
        cues_json=None, dialog_text=None, recognizer="phonetic",
        start_frame=None, emotion=1.0, emotion_attr=None, namespace=None,
        import_sound=True, tangent="auto", **settings_kw):
    """Point d'entree sans UI. Renvoie (plan, nkeys, missing)."""
    library = core.PoseLibrary(happy_folder, sad_folder)

    offset = 0.0
    if not audio:
        audio, offset = scene_audio()
        if not audio:
            raise ValueError("Aucun audio donne et aucun son dans la scene")
    if start_frame is None:
        start_frame = offset if offset else cmds.playbackOptions(q=True, min=True)

    if cues_json:
        cues = core.load_cues(cues_json)
    else:
        cues = core.run_rhubarb(rhubarb_exe, audio, dialog_text, recognizer)
    energy = core.audio_energy(audio)

    settings = core.Settings(fps=scene_fps(), start_frame=float(start_frame), **settings_kw)
    plan = core.plan_keys(cues, settings, energy, available=set(library.visemes()))

    if import_sound and audio.lower().endswith((".wav", ".aif", ".aiff", ".mp3", ".ogg")):
        try:
            import_audio(audio, start_frame)
        except Exception as exc:
            cmds.warning("Audio non importe : %s" % exc)

    nkeys, missing = apply_plan(library, plan, emotion, emotion_attr, namespace, tangent)
    return plan, nkeys, missing
