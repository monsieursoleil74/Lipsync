# -*- coding: utf-8 -*-
"""
Coeur de l'auto lipsync : aucune dependance a Maya ici.

Pipeline :
    audio (.wav)  --Rhubarb-->  cues (visemes horodates)
    cues + energie audio       --plan_keys-->  liste de cles (frame, viseme, poids)
    poses Studio Library       --PoseLibrary--> deltas par rapport a Neutral
    cle + library + emotion    --blend_values--> valeurs d'attributs a keyer

Tout est lineaire : valeur = neutral + poids * (emotion * delta_happy + (1 - emotion) * delta_sad)
"""
import json
import math
import os
import re
import subprocess
import tempfile
import wave

# ---------------------------------------------------------------------------
# Visemes de la charte
# ---------------------------------------------------------------------------

VISEMES = [
    "Neutral", "A", "Ah", "Ai", "Ch", "E", "i",
    "MBP_a", "MBP_o", "OoEn", "OuUOn",
    "SZTDN_a", "SZTDN_o", "VF_a", "VF_o",
]

# Visemes qui existent en variante (a) / (o)
VARIANT_BASES = ("MBP", "SZTDN", "VF")

# Formes Rhubarb -> viseme de la charte (sans variante).
# A fermeture, B dents serrees, C bouche semi ouverte, D grande ouverture,
# E "o" ferme, F "ou" pince, G f/v, H langue levee (l), X repos.
DEFAULT_MAPPING = {
    "A": "MBP",
    "B": "SZTDN",
    "C": "E",
    "D": "A",
    "D_loud": "Ah",      # D quand l'audio est fort
    "E": "OoEn",
    "F": "OuUOn",
    "G": "VF",
    "H": "i",
    "X": "Neutral",
}

# Poids cible par viseme : jamais 100 % sauf les fermetures.
TARGET_WEIGHTS = {
    "Neutral": 0.0,
    "A": 0.85, "Ah": 0.9, "Ai": 0.7, "Ch": 0.65, "E": 0.75, "i": 0.65,
    "MBP": 1.0, "OoEn": 0.75, "OuUOn": 0.85, "SZTDN": 0.6, "VF": 0.65,
}

# Visemes dont le poids ne depend ni de la duree ni de l'energie (bouche fermee)
CLOSURES = ("MBP",)
# Formes Rhubarb considerees comme voyelles (sensibles a l'energie)
VOWEL_SHAPES = ("C", "D", "E", "F")
# Formes rondes -> variante (o), formes ouvertes -> variante (a)
ROUND_SHAPES = ("E", "F")
OPEN_SHAPES = ("B", "C", "D", "H")

NUMERIC_TYPES = ("doubleLinear", "doubleAngle", "double", "float", "long", "short", "int", "byte")


def canon(name):
    """Normalise un nom de pose : 'h_MBP (a).pose' -> 'mbpa'."""
    base = os.path.basename(name)
    if base.lower().endswith(".pose"):
        base = base[:-5]
    elif base.lower().endswith(".json"):
        base = base[:-5]
    base = base.strip()
    # prefixe d'une lettre type 'h_' / 's_' (happy / sad)
    m = re.match(r"^[A-Za-z]_(.*)$", base)
    if m:
        base = m.group(1)
    return _squash(base)


def _squash(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


CANON_TO_VISEME = {_squash(v): v for v in VISEMES}


def viseme_from_pose_name(name):
    return CANON_TO_VISEME.get(canon(name))


# ---------------------------------------------------------------------------
# Lecture des poses Studio Library
# ---------------------------------------------------------------------------

def load_pose_file(path):
    """Lit un pose.json Studio Library -> {ctrl: {attr: valeur}} (numeriques seulement)."""
    if os.path.isdir(path):
        path = os.path.join(path, "pose.json")
    with open(path, "r") as f:
        data = json.load(f)
    objects = data.get("objects", data)
    result = {}
    for ctrl, info in objects.items():
        attrs = info.get("attrs", info) if isinstance(info, dict) else {}
        values = {}
        for attr, spec in attrs.items():
            if isinstance(spec, dict):
                if spec.get("type") not in NUMERIC_TYPES:
                    continue
                value = spec.get("value")
            else:
                value = spec
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            values[attr] = float(value)
        if values:
            result[ctrl] = values
    return result


def scan_pose_folder(folder):
    """Parcourt un dossier de library -> {viseme: pose_dict}. Ignore ce qui n'est pas dans la charte."""
    poses = {}
    if not folder or not os.path.isdir(folder):
        return poses
    for root, dirs, files in os.walk(folder):
        if root.lower().endswith(".pose") and "pose.json" in files:
            vis = viseme_from_pose_name(root)
            if vis:
                poses[vis] = load_pose_file(os.path.join(root, "pose.json"))
            dirs[:] = []
            continue
        for fn in files:
            if fn.lower().endswith(".json") and fn.lower() != "pose.json":
                vis = viseme_from_pose_name(fn)
                if vis:
                    poses[vis] = load_pose_file(os.path.join(root, fn))
    return poses


def short_name(ctrl):
    return ctrl.split("|")[-1].split(":")[-1]


class PoseSet(object):
    """Un jeu de poses (ex : HAPPY) exprime en deltas par rapport a sa pose Neutral."""

    def __init__(self, poses):
        if "Neutral" not in poses:
            raise ValueError("Pose 'Neutral' introuvable dans ce jeu de poses")
        # tout est indexe par nom court de controleur
        self.neutral = {short_name(c): dict(a) for c, a in poses["Neutral"].items()}
        self.deltas = {}
        for vis, pose in poses.items():
            if vis == "Neutral":
                continue
            delta = {}
            for ctrl, attrs in pose.items():
                sn = short_name(ctrl)
                base = self.neutral.get(sn, {})
                d = {}
                for attr, value in attrs.items():
                    if attr in base:
                        diff = value - base[attr]
                        if abs(diff) > 1e-6:
                            d[attr] = diff
                if d:
                    delta[sn] = d
            self.deltas[vis] = delta

    def visemes(self):
        return sorted(self.deltas.keys())


class PoseLibrary(object):
    """Plusieurs jeux de poses (happy / sad) blendables par un parametre emotion in [0, 1]."""

    def __init__(self, happy_folder=None, sad_folder=None):
        self.happy = PoseSet(scan_pose_folder(happy_folder)) if happy_folder else None
        self.sad = PoseSet(scan_pose_folder(sad_folder)) if sad_folder else None
        if not self.happy and not self.sad:
            raise ValueError("Aucun jeu de poses charge")
        if not self.happy:
            self.happy = self.sad
        if not self.sad:
            self.sad = self.happy

    def available(self, viseme):
        return viseme in self.happy.deltas or viseme in self.sad.deltas

    def visemes(self):
        return sorted(set(self.happy.visemes()) | set(self.sad.visemes()))

    def controllers(self):
        """Tous les controleurs / attributs touches par au moins une pose."""
        attrs = {}
        for pset in (self.happy, self.sad):
            for delta in pset.deltas.values():
                for ctrl, a in delta.items():
                    attrs.setdefault(ctrl, set()).update(a.keys())
        return attrs

    def blend_values(self, viseme, weight, emotion=1.0):
        """Valeurs finales {ctrl: {attr: valeur}} pour un viseme a un poids donne."""
        emotion = min(1.0, max(0.0, emotion))
        out = {}
        for ctrl, attrs in self.controllers().items():
            nh = self.happy.neutral.get(ctrl, {})
            ns = self.sad.neutral.get(ctrl, {})
            dh = self.happy.deltas.get(viseme, {}).get(ctrl, {})
            ds = self.sad.deltas.get(viseme, {}).get(ctrl, {})
            values = {}
            for attr in attrs:
                base_h = nh.get(attr, ns.get(attr))
                base_s = ns.get(attr, nh.get(attr))
                if base_h is None:
                    continue
                base = emotion * base_h + (1.0 - emotion) * base_s
                delta = emotion * dh.get(attr, 0.0) + (1.0 - emotion) * ds.get(attr, 0.0)
                values[attr] = base + weight * delta
            if values:
                out[ctrl] = values
        return out


# ---------------------------------------------------------------------------
# Rhubarb
# ---------------------------------------------------------------------------

def run_rhubarb(exe, audio_path, dialog_text=None, recognizer="phonetic", out_json=None):
    """Lance Rhubarb Lip Sync et renvoie la liste de cues [{start, end, value}]."""
    if not exe or not os.path.isfile(exe):
        raise IOError("Executable Rhubarb introuvable : %r" % exe)
    if not os.path.isfile(audio_path):
        raise IOError("Fichier audio introuvable : %r" % audio_path)
    ext = os.path.splitext(audio_path)[1].lower()
    if ext not in (".wav", ".ogg"):
        raise ValueError("Rhubarb ne lit que le WAV et l'OGG, pas %s" % ext)
    if out_json is None:
        out_json = os.path.join(tempfile.gettempdir(), "auto_lipsync_cues.json")
    cmd = [exe, "-f", "json", "-r", recognizer, "--extendedShapes", "GHX", "-o", out_json]
    dialog_file = None
    if dialog_text and dialog_text.strip():
        fd, dialog_file = tempfile.mkstemp(suffix=".txt", prefix="auto_lipsync_dialog_")
        with os.fdopen(fd, "w") as f:
            f.write(dialog_text.strip())
        cmd += ["-d", dialog_file]
    cmd.append(audio_path)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, err = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("Rhubarb a echoue (%d) :\n%s" % (proc.returncode, err.decode("utf-8", "replace")))
    finally:
        if dialog_file and os.path.exists(dialog_file):
            os.remove(dialog_file)
    return load_cues(out_json)


def load_cues(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)
    cues = []
    for c in data.get("mouthCues", []):
        cues.append({"start": float(c["start"]), "end": float(c["end"]), "value": str(c["value"])})
    return cues


# ---------------------------------------------------------------------------
# Energie audio (RMS), pure python
# ---------------------------------------------------------------------------

def audio_energy(wav_path, window=0.01):
    """Enveloppe RMS normalisee [0, 1] par fenetre -> liste de (temps, energie)."""
    try:
        wf = wave.open(wav_path, "rb")
    except Exception:
        return []
    try:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
    finally:
        wf.close()
    if not raw or width not in (1, 2, 3, 4):
        return []
    step = max(1, int(rate * window))
    frame_bytes = width * channels
    rms_list = []
    try:
        import audioop  # rapide, dispo jusqu'a Python 3.12 (Maya <= 2026)
        for i in range(0, nframes, step):
            chunk = raw[i * frame_bytes:(i + step) * frame_bytes]
            if not chunk:
                break
            rms_list.append((i / float(rate), audioop.rms(chunk, width)))
    except ImportError:
        import struct
        signed = width != 1
        for i in range(0, nframes, step):
            chunk = raw[i * frame_bytes:(i + step) * frame_bytes]
            if not chunk:
                break
            total = 0.0
            count = 0
            for j in range(0, len(chunk) - width + 1, width):
                v = int.from_bytes(chunk[j:j + width], "little", signed=signed)
                if not signed:
                    v -= 128
                total += v * v
                count += 1
            rms_list.append((i / float(rate), math.sqrt(total / count) if count else 0.0))
    if not rms_list:
        return []
    values = sorted(r for _, r in rms_list)
    lo = values[int(len(values) * 0.10)]
    hi = values[int(len(values) * 0.95) - 1] if len(values) > 1 else values[0]
    span = hi - lo
    out = []
    for t, r in rms_list:
        e = (r - lo) / span if span > 0 else 0.0
        out.append((t, min(1.0, max(0.0, e))))
    return out


def energy_for_interval(energy, start, end):
    """Energie moyenne sur [start, end] (secondes), 0.5 si pas d'info."""
    if not energy:
        return 0.5
    vals = [e for t, e in energy if start <= t < end]
    if not vals:
        # intervalle plus court qu'une fenetre : plus proche voisin
        nearest = min(energy, key=lambda te: abs(te[0] - start))
        return nearest[1]
    return sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# Planification des cles
# ---------------------------------------------------------------------------

class Settings(object):
    def __init__(self, **kw):
        self.fps = 24.0
        self.start_frame = 1.0          # frame ou commence l'audio
        self.lead_frames = 1.5          # la bouche precede le son
        self.intensity = 1.0            # multiplicateur global
        self.energy_influence = 0.5     # 0 = ignore le volume, 1 = suit le volume
        self.full_frames = 5.0          # duree (frames) a partir de laquelle un phoneme atteint son poids cible
        self.min_duration_factor = 0.4  # plancher pour les phonemes tres courts
        self.hold_min_frames = 6.0      # au dela, on pose 2 cles pour tenir la forme
        self.hold_margin = 2.0          # marge (frames) entre le bord du phoneme et la cle de tenue
        self.loud_threshold = 0.7       # energie a partir de laquelle D devient D_loud
        self.mapping = dict(DEFAULT_MAPPING)
        self.target_weights = dict(TARGET_WEIGHTS)
        for k, v in kw.items():
            if not hasattr(self, k):
                raise AttributeError("Reglage inconnu : %s" % k)
            setattr(self, k, v)


def resolve_variant(cues, index):
    """(a) ou (o) selon la voyelle voisine. On regarde d'abord la suivante (anticipation)."""
    for j in (index + 1, index + 2, index - 1, index - 2):
        if 0 <= j < len(cues):
            shape = cues[j]["value"]
            if shape in ROUND_SHAPES:
                return "o"
            if shape in OPEN_SHAPES:
                return "a"
    return "a"


def _viseme_with_variant(base, variant):
    if base in VARIANT_BASES:
        return "%s_%s" % (base, variant)
    return base


def plan_keys(cues, settings, energy=None, available=None):
    """Transforme les cues Rhubarb en cles.

    Renvoie une liste de dicts {frame, viseme, weight, shape, start, end}
    triee par frame. Une cle par phoneme (au centre), deux pour les longs.
    Entre deux cles, Maya interpole : c'est ca le crossfade de coarticulation.
    """
    s = settings
    keys = {}
    for i, cue in enumerate(cues):
        shape = cue["value"]
        base = s.mapping.get(shape)
        if base is None:
            continue
        e = energy_for_interval(energy, cue["start"], cue["end"]) if energy else 0.5
        if shape == "D" and e >= s.loud_threshold and s.mapping.get("D_loud"):
            base = s.mapping["D_loud"]
        viseme = _viseme_with_variant(base, resolve_variant(cues, i))
        if available is not None and viseme not in available and viseme != "Neutral":
            # variante absente de la library -> on tente l'autre, puis on saute
            other = _viseme_with_variant(base, "a" if viseme.endswith("_o") else "o")
            if other in available:
                viseme = other
            else:
                continue

        target = s.target_weights.get(base, 0.7)
        dur_frames = (cue["end"] - cue["start"]) * s.fps
        if base in CLOSURES or viseme == "Neutral":
            weight = target
        else:
            dur_factor = min(1.0, max(s.min_duration_factor, dur_frames / s.full_frames))
            if shape in VOWEL_SHAPES:
                energy_factor = (1.0 - s.energy_influence) + s.energy_influence * (0.5 + 0.6 * e)
            else:
                energy_factor = 1.0
            weight = target * dur_factor * energy_factor * s.intensity
        weight = min(1.0, max(0.0, weight))

        f_start = s.start_frame + cue["start"] * s.fps - s.lead_frames
        f_end = s.start_frame + cue["end"] * s.fps - s.lead_frames
        if dur_frames >= s.hold_min_frames:
            frames = [f_start + s.hold_margin, f_end - s.hold_margin]
        else:
            frames = [(f_start + f_end) * 0.5]
        for fr in frames:
            frame = float(round(fr))
            entry = {"frame": frame, "viseme": viseme, "weight": weight,
                     "shape": shape, "start": cue["start"], "end": cue["end"]}
            prev = keys.get(frame)
            # collision sur la meme frame : la forme la plus marquee gagne
            if prev is None or weight > prev["weight"]:
                keys[frame] = entry
    return [keys[f] for f in sorted(keys)]


def plan_summary(plan):
    if not plan:
        return "Aucune cle"
    counts = {}
    for k in plan:
        counts[k["viseme"]] = counts.get(k["viseme"], 0) + 1
    lines = ["%d cles de %g a %g" % (len(plan), plan[0]["frame"], plan[-1]["frame"])]
    for vis in sorted(counts):
        lines.append("  %-10s %d" % (vis, counts[vis]))
    return "\n".join(lines)
