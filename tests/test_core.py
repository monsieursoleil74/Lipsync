# -*- coding: utf-8 -*-
"""Tests du coeur, sans Maya :  python -m pytest tests  ou  python tests/test_core.py"""
import json
import math
import os
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from maya_auto_lipsync import core  # noqa: E402


def make_pose(folder, name, values):
    """Cree un .pose Studio Library : values = {ctrl: {attr: v}}."""
    d = os.path.join(folder, name + ".pose")
    os.makedirs(d)
    objects = {}
    for ctrl, attrs in values.items():
        objects[ctrl] = {"attrs": {
            a: {"type": "doubleAngle" if a.startswith("rotate") else "doubleLinear", "value": v}
            for a, v in attrs.items()}}
        objects[ctrl]["attrs"]["visibility"] = {"type": "bool", "value": True}
    with open(os.path.join(d, "pose.json"), "w") as f:
        json.dump({"metadata": {"version": "1.0"}, "objects": objects}, f)


def build_library(root):
    happy = os.path.join(root, "PHONEM HAPPY")
    sad = os.path.join(root, "PHONEM SAD")
    os.makedirs(happy)
    os.makedirs(sad)
    jaw = "rig:jaw_ctrl"
    lip = "rig:lip_ctrl"
    # happy : neutral jaw 0, smile 2
    make_pose(happy, "h_Neutral", {jaw: {"translateY": 0.0}, lip: {"translateX": 2.0, "rotateZ": 0.0}})
    make_pose(happy, "h_A", {jaw: {"translateY": -5.0}, lip: {"translateX": 2.0, "rotateZ": 0.0}})
    make_pose(happy, "h_MBP (a)", {jaw: {"translateY": 0.0}, lip: {"translateX": 2.0, "rotateZ": 10.0}})
    make_pose(happy, "h_MBP (o)", {jaw: {"translateY": 0.0}, lip: {"translateX": 0.0, "rotateZ": 10.0}})
    make_pose(happy, "h_Oo En", {jaw: {"translateY": -2.0}, lip: {"translateX": -1.0, "rotateZ": 0.0}})
    make_pose(happy, "h_Ch ", {jaw: {"translateY": -1.0}, lip: {"translateX": 2.0, "rotateZ": 0.0}})
    # sad : neutral smile -2
    make_pose(sad, "s_Neutral", {jaw: {"translateY": 0.0}, lip: {"translateX": -2.0, "rotateZ": 0.0}})
    make_pose(sad, "s_A", {jaw: {"translateY": -4.0}, lip: {"translateX": -2.0, "rotateZ": 0.0}})
    make_pose(sad, "s_MBP (a)", {jaw: {"translateY": 0.0}, lip: {"translateX": -2.0, "rotateZ": 8.0}})
    make_pose(sad, "s_Oo En", {jaw: {"translateY": -2.0}, lip: {"translateX": -3.0, "rotateZ": 0.0}})
    return happy, sad


def make_wav(path, seconds=1.0, rate=16000, loud_from=0.5):
    wf = wave.open(path, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(rate)
    frames = []
    for i in range(int(rate * seconds)):
        t = i / float(rate)
        amp = 3000 if t < loud_from else 20000
        frames.append(struct.pack("<h", int(amp * math.sin(2 * math.pi * 220 * t))))
    wf.writeframes(b"".join(frames))
    wf.close()


class CanonTest(unittest.TestCase):
    def test_names_from_chart(self):
        cases = {
            "h_A.pose": "A", "h_Ah.pose": "Ah", "h_Ai.pose": "Ai", "h_Ch .pose": "Ch", "h_E.pose": "E",
            "h_MBP (a).pose": "MBP_a", "h_MBP (o).pose": "MBP_o", "h_Neutral.pose": "Neutral",
            "h_Oo En.pose": "OoEn", "h_Ou U On.pose": "OuUOn", "s_SZTDN (a).pose": "SZTDN_a",
            "s_SZTDN (o).pose": "SZTDN_o", "s_V F (a).pose": "VF_a", "s_V F (o).pose": "VF_o", "s_i.pose": "i",
            "/lib/PHONEM SAD/s_V F (o).pose": "VF_o", "random.pose": None,
        }
        for name, expected in cases.items():
            self.assertEqual(core.viseme_from_pose_name(name), expected, name)


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.happy, self.sad = build_library(self.tmp)
        self.lib = core.PoseLibrary(self.happy, self.sad)

    def test_scan_and_deltas(self):
        self.assertEqual(self.lib.visemes(), ["A", "Ch", "MBP_a", "MBP_o", "OoEn"])
        # delta exprime par rapport au neutral, en noms courts, sans attribut bool
        self.assertEqual(self.lib.happy.deltas["A"], {"jaw_ctrl": {"translateY": -5.0}})
        self.assertNotIn("visibility", self.lib.happy.neutral["lip_ctrl"])

    def test_blend_weight(self):
        full = self.lib.blend_values("A", 1.0, emotion=1.0)
        half = self.lib.blend_values("A", 0.5, emotion=1.0)
        self.assertAlmostEqual(full["jaw_ctrl"]["translateY"], -5.0)
        self.assertAlmostEqual(half["jaw_ctrl"]["translateY"], -2.5)
        # le smile du neutral happy est conserve
        self.assertAlmostEqual(half["lip_ctrl"]["translateX"], 2.0)

    def test_blend_emotion(self):
        mid = self.lib.blend_values("A", 1.0, emotion=0.5)
        self.assertAlmostEqual(mid["jaw_ctrl"]["translateY"], -4.5)   # (-5 + -4) / 2
        self.assertAlmostEqual(mid["lip_ctrl"]["translateX"], 0.0)    # (2 + -2) / 2
        sad = self.lib.blend_values("MBP_a", 1.0, emotion=0.0)
        self.assertAlmostEqual(sad["lip_ctrl"]["rotateZ"], 8.0)

    def test_missing_viseme_in_one_set_falls_back_to_neutral(self):
        # MBP_o n'existe qu'en happy : en sad il vaut neutral sad
        v = self.lib.blend_values("MBP_o", 1.0, emotion=0.0)
        self.assertAlmostEqual(v["lip_ctrl"]["translateX"], -2.0)
        self.assertAlmostEqual(v["lip_ctrl"]["rotateZ"], 0.0)

    def test_single_set(self):
        lib = core.PoseLibrary(self.happy, None)
        self.assertIs(lib.sad, lib.happy)
        self.assertAlmostEqual(lib.blend_values("A", 1.0, 0.0)["jaw_ctrl"]["translateY"], -5.0)


CUES = [
    {"start": 0.00, "end": 0.20, "value": "X"},
    {"start": 0.20, "end": 0.25, "value": "A"},   # fermeture courte
    {"start": 0.25, "end": 0.45, "value": "D"},   # voyelle longue
    {"start": 0.45, "end": 0.50, "value": "B"},
    {"start": 0.50, "end": 0.55, "value": "A"},   # fermeture avant un "o"
    {"start": 0.55, "end": 0.80, "value": "E"},
    {"start": 0.80, "end": 1.00, "value": "X"},
]


class PlanTest(unittest.TestCase):
    def test_keys_and_weights(self):
        s = core.Settings(fps=24.0, start_frame=1.0, lead_frames=0.0, energy_influence=0.0)
        plan = core.plan_keys(CUES, s)
        by_shape = {}
        for k in plan:
            by_shape.setdefault(k["shape"], []).append(k)
        # fermetures toujours a 100 %, meme courtes
        for k in by_shape["A"]:
            self.assertAlmostEqual(k["weight"], 1.0)
        # variante choisie selon la voyelle suivante
        self.assertEqual(by_shape["A"][0]["viseme"], "MBP_a")
        self.assertEqual(by_shape["A"][1]["viseme"], "MBP_o")
        # voyelle de 0.2 s = 4.8 frames < 5 -> un peu en dessous de la cible
        d = by_shape["D"][0]
        self.assertEqual(d["viseme"], "A")
        self.assertLess(d["weight"], core.TARGET_WEIGHTS["A"])
        self.assertGreater(d["weight"], core.TARGET_WEIGHTS["A"] * 0.9)
        # consonne de 1.2 frames -> plancher 0.4
        b = by_shape["B"][0]
        self.assertAlmostEqual(b["weight"], core.TARGET_WEIGHTS["SZTDN"] * 0.4)
        # phonemes longs : deux cles de tenue, repos a 0
        self.assertEqual(len(by_shape["E"]), 2)
        self.assertEqual(len(by_shape["X"]), 2)  # 4.8 frames < seuil de tenue
        self.assertTrue(all(k["weight"] == 0.0 for k in by_shape["X"]))
        frames = [k["frame"] for k in plan]
        self.assertEqual(frames, sorted(frames))
        self.assertEqual(len(set(frames)), len(frames))

    def test_lead_and_start_frame(self):
        s0 = core.Settings(fps=24.0, start_frame=1.0, lead_frames=0.0)
        s1 = core.Settings(fps=24.0, start_frame=101.0, lead_frames=2.0)
        p0 = core.plan_keys(CUES, s0)
        p1 = core.plan_keys(CUES, s1)
        self.assertEqual([k["frame"] + 98 for k in p0], [k["frame"] for k in p1])

    def test_energy_scales_vowels_only(self):
        energy = [(t / 100.0, 1.0) for t in range(100)]
        quiet = [(t / 100.0, 0.0) for t in range(100)]
        s = core.Settings(fps=24.0, energy_influence=1.0)
        loud_plan = core.plan_keys(CUES, s, energy)
        quiet_plan = core.plan_keys(CUES, s, quiet)
        loud = {(k["shape"], k["frame"]): k for k in loud_plan}
        for k in quiet_plan:
            lk = loud.get((k["shape"], k["frame"]))
            if lk is None:
                continue
            if k["shape"] in core.VOWEL_SHAPES:
                self.assertLess(k["weight"], lk["weight"])
            else:
                self.assertAlmostEqual(k["weight"], lk["weight"])
        # D fort -> Ah
        self.assertIn("Ah", [k["viseme"] for k in loud_plan])
        self.assertNotIn("Ah", [k["viseme"] for k in quiet_plan])

    def test_available_filter(self):
        s = core.Settings(fps=24.0)
        plan = core.plan_keys(CUES, s, available={"A", "MBP_a", "Neutral"})
        visemes = {k["viseme"] for k in plan}
        self.assertEqual(visemes, {"A", "MBP_a", "Neutral"})  # MBP_o -> MBP_a, B et E sautes

    def test_custom_mapping(self):
        s = core.Settings(fps=24.0, mapping={"D": "Ai", "X": "Neutral"})
        plan = core.plan_keys(CUES, s)
        self.assertEqual({k["viseme"] for k in plan}, {"Ai", "Neutral"})


class AudioTest(unittest.TestCase):
    def test_energy_envelope(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "test.wav")
        make_wav(path, seconds=1.0, loud_from=0.5)
        energy = core.audio_energy(path)
        self.assertTrue(energy)
        self.assertLess(core.energy_for_interval(energy, 0.1, 0.4), 0.2)
        self.assertGreater(core.energy_for_interval(energy, 0.6, 0.9), 0.8)
        self.assertEqual(core.energy_for_interval([], 0, 1), 0.5)

    def test_missing_file(self):
        self.assertEqual(core.audio_energy("/nope.wav"), [])


class CuesTest(unittest.TestCase):
    def test_load_cues(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "cues.json")
        with open(path, "w") as f:
            json.dump({"metadata": {"duration": 1.0}, "mouthCues": CUES}, f)
        self.assertEqual(core.load_cues(path), CUES)

    def test_rhubarb_missing_exe(self):
        with self.assertRaises(IOError):
            core.run_rhubarb("/nope/rhubarb", "/nope.wav")


from maya_auto_lipsync import phonemes_wav2vec as w2v  # noqa: E402


class Wav2VecMappingTest(unittest.TestCase):
    def test_ipa_mapping(self):
        cases = {
            "p": ("MBP", "closure"), "m": ("MBP", "closure"), "f": ("VF", "consonant"),
            "ʃ": ("Ch", "consonant"), "s": ("SZTDN", "consonant"), "ʁ": ("SZTDN", "consonant"),
            "a": ("A", "open"), "ɑ̃": ("Ah", "open"), "ɛ̃": ("E", "open"), "iː": ("i", "open"),
            "ˈa": ("A", "open"), "ɔ̃": ("OoEn", "round"), "u": ("OuUOn", "round"), "w": ("OuUOn", "round"),
            "aɪ": ("Ai", "open"), "|": ("Neutral", "rest"), "h": (None, None), "<pad>": (None, None),
        }
        for ipa, expected in cases.items():
            self.assertEqual(w2v.ipa_to_viseme(ipa), expected, ipa)

    def test_segments_to_cues(self):
        # "bonjour" : b ɔ̃ ʒ u ʁ, avec un silence avant et un trou de blanks CTC entre phones
        segs = [(0.30, 0.32, "b"), (0.34, 0.36, "ɔ̃"), (0.48, 0.50, "ʒ"), (0.52, 0.54, "u"), (0.60, 0.62, "ʁ"),
                (0.90, 0.92, "h")]
        cues = w2v.segments_to_cues(segs, duration=1.2)
        self.assertEqual(cues[0]["viseme"], "Neutral")                 # silence initial
        self.assertEqual([c["viseme"] for c in cues], ["Neutral", "MBP", "OoEn", "Ch", "OuUOn", "SZTDN", "Neutral"])
        # chaque phone dure jusqu'au suivant quand le trou est petit
        self.assertAlmostEqual(cues[1]["end"], 0.34)
        self.assertAlmostEqual(cues[2]["end"], 0.48)
        # le dernier phone ne s'etire pas jusqu'au 'h' ignore (trou de 0.28 > max_gap)
        self.assertAlmostEqual(cues[5]["end"], 0.62)
        self.assertAlmostEqual(cues[6]["start"], 0.62)
        self.assertAlmostEqual(cues[6]["end"], 1.2)
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-9)


class PhonemePlanTest(unittest.TestCase):
    def setUp(self):
        segs = [(0.10, 0.12, "p"), (0.14, 0.16, "a"), (0.30, 0.32, "s"), (0.34, 0.36, "ɔ̃"), (0.50, 0.52, "m"),
                (0.54, 0.56, "u"), (0.70, 0.72, "ʃ"), (0.74, 0.76, "aɪ")]
        self.cues = w2v.segments_to_cues(segs, duration=1.0)

    def test_variants_and_visemes_from_kind(self):
        s = core.Settings(fps=24.0, energy_influence=0.0)
        plan = core.plan_keys(self.cues, s)
        by_value = {k["shape"]: k for k in plan}
        self.assertEqual(by_value["p"]["viseme"], "MBP_a")      # voyelle suivante 'a'
        self.assertEqual(by_value["s"]["viseme"], "SZTDN_o")    # voyelle suivante 'ɔ̃'
        self.assertEqual(by_value["m"]["viseme"], "MBP_o")      # voyelle suivante 'u'
        self.assertEqual(by_value["ʃ"]["viseme"], "Ch")
        self.assertEqual(by_value["aɪ"]["viseme"], "Ai")
        self.assertAlmostEqual(by_value["p"]["weight"], 1.0)
        self.assertLess(by_value["a"]["weight"], 1.0)

    def test_loud_upgrade_and_roundtrip_json(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "cues.json")
        with open(path, "w") as f:
            json.dump({"mouthCues": self.cues}, f)
        loaded = core.load_cues(path)
        self.assertEqual(loaded[1]["viseme"], "MBP")
        loud = [(t / 100.0, 1.0) for t in range(100)]
        plan = core.plan_keys(loaded, core.Settings(fps=24.0, energy_influence=1.0), loud,
                              available={"A", "Ah", "MBP_a", "MBP_o", "SZTDN_o", "OoEn", "OuUOn", "Ch", "Ai", "Neutral"})
        self.assertIn("Ah", [k["viseme"] for k in plan])
        plan = core.plan_keys(loaded, core.Settings(fps=24.0, energy_influence=1.0), loud,
                              available={"A", "MBP_a", "Neutral"})
        self.assertNotIn("Ah", [k["viseme"] for k in plan])  # Ah absent de la library -> reste A
        self.assertIn("A", [k["viseme"] for k in plan])

    def test_missing_python(self):
        with self.assertRaises(IOError):
            core.run_wav2vec("/nope/python", "/nope.wav")


if __name__ == "__main__":
    unittest.main()
