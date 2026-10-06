# -*- coding: utf-8 -*-
"""Fenetre Maya de l'auto lipsync."""
import json
import os

from maya import cmds

from . import core
from . import maya_apply

WINDOW = "autoLipsyncWin"
PREFS = os.path.join(cmds.internalVar(userPrefDir=True), "auto_lipsync_prefs.json")

RHUBARB_SHAPES = ["A", "B", "C", "D", "D_loud", "E", "F", "G", "H", "X"]
SHAPE_HELP = {
    "A": "fermeture (m, b, p)", "B": "dents serrees (s, t, d, k...)", "C": "semi ouvert (e, è)",
    "D": "grande ouverture (a)", "D_loud": "grande ouverture, audio fort", "E": "o ferme",
    "F": "ou pince", "G": "f / v", "H": "l (langue levee)", "X": "repos",
}
MAP_CHOICES = ["(aucun)", "Neutral", "A", "Ah", "Ai", "Ch", "E", "i", "MBP", "OoEn", "OuUOn", "SZTDN", "VF"]


class LipsyncUI(object):
    def __init__(self):
        self.w = {}
        self.prefs = self._load_prefs()
        self.build()

    # ------------------------------------------------------------------ prefs
    def _load_prefs(self):
        try:
            with open(PREFS, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_prefs(self):
        data = {
            "happy": self.val("happy"), "sad": self.val("sad"), "rhubarb": self.val("rhubarb"),
            "namespace": self.val("namespace"), "recognizer": self.val("recognizer"),
            "engine": cmds.optionMenuGrp(self.w["engine"], q=True, value=True),
            "python": self.val("python"), "lang": self.val("lang"),
            "mapping": self.mapping(),
        }
        try:
            with open(PREFS, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # --------------------------------------------------------------------- ui
    def build(self):
        if cmds.window(WINDOW, exists=True):
            cmds.deleteUI(WINDOW)
        cmds.window(WINDOW, title="Auto Lipsync", widthHeight=(460, 720), sizeable=True)
        cmds.scrollLayout(childResizable=True)
        col = cmds.columnLayout(adjustableColumn=True, rowSpacing=4, columnOffset=("both", 6))

        cmds.frameLayout(label="Library (Studio Library)", collapsable=True, marginWidth=4, marginHeight=4)
        self._path_row("happy", "Dossier PHONEM HAPPY", self.prefs.get("happy", ""), folder=True)
        self._path_row("sad", "Dossier PHONEM SAD", self.prefs.get("sad", ""), folder=True)
        self.w["namespace"] = cmds.textFieldGrp(label="Namespace du rig", text=self.prefs.get("namespace", ""),
                                                columnWidth2=(130, 280), ann="Vide = recherche par nom court")
        cmds.setParent("..")

        cmds.frameLayout(label="Audio", collapsable=True, marginWidth=4, marginHeight=4)
        self._path_row("audio", "Fichier .wav", "", folder=False, filt="Audio (*.wav *.ogg)")
        cmds.button(label="Prendre le son du shot (time slider)", c=lambda *_: self._from_scene())
        self.w["start"] = cmds.floatFieldGrp(label="Frame de depart", value1=cmds.playbackOptions(q=True, min=True),
                                             columnWidth2=(130, 80))
        self.w["import"] = cmds.checkBoxGrp(label="", label1="Charger l'audio dans la timeline", value1=True,
                                            columnWidth2=(130, 250))
        cmds.text(label="Texte du dialogue (optionnel, ameliore la detection) :", align="left")
        self.w["dialog"] = cmds.scrollField(height=60, wordWrap=True)
        cmds.setParent("..")

        cmds.frameLayout(label="Moteur de phonemes", collapsable=True, marginWidth=4, marginHeight=4)
        self.w["engine"] = cmds.optionMenuGrp(label="Moteur", columnWidth2=(130, 250),
                                              ann="wav2vec2 = vrais phonemes, multilingue, utilise toute la charte")
        for eng in ("wav2vec2 (recommande)", "rhubarb"):
            cmds.menuItem(label=eng)
        cmds.optionMenuGrp(self.w["engine"], e=True, value=self.prefs.get("engine", "wav2vec2 (recommande)"))
        cmds.text(label="wav2vec2 : Python externe avec torch + transformers (voir README)", align="left")
        self._path_row("python", "Executable python", self.prefs.get("python", ""), folder=False, filt="*")
        self.w["lang"] = cmds.textFieldGrp(label="Langue (avec texte)", text=self.prefs.get("lang", "fr-fr"),
                                           columnWidth2=(130, 100), ann="code espeak : fr-fr, en-us, en-gb...")
        cmds.text(label="rhubarb :", align="left")
        self._path_row("rhubarb", "Executable rhubarb", self.prefs.get("rhubarb", ""), folder=False, filt="*")
        self.w["recognizer"] = cmds.optionMenuGrp(label="Recognizer", columnWidth2=(130, 150),
                                                  ann="phonetic = toutes langues (francais), pocketSphinx = anglais")
        for r in ("phonetic", "pocketSphinx"):
            cmds.menuItem(label=r)
        cmds.optionMenuGrp(self.w["recognizer"], e=True, value=self.prefs.get("recognizer", "phonetic"))
        self._path_row("cues", "Ou JSON deja calcule", "", folder=False, filt="JSON (*.json)")
        cmds.setParent("..")

        cmds.frameLayout(label="Blending", collapsable=True, marginWidth=4, marginHeight=4)
        self.w["emotion"] = cmds.floatSliderGrp(label="Emotion  sad < > happy", field=True, min=0, max=1, value=1.0,
                                                columnWidth3=(130, 50, 230))
        self.w["emotion_attr"] = cmds.textFieldGrp(label="Attribut emotion anime", text="", columnWidth2=(130, 280),
                                                   ann="ex: face_ctrl.happy  (0 = sad, 1 = happy), prioritaire sur le slider")
        self.w["intensity"] = cmds.floatSliderGrp(label="Intensite", field=True, min=0.2, max=1.5, value=1.0,
                                                  columnWidth3=(130, 50, 230))
        self.w["energy"] = cmds.floatSliderGrp(label="Influence du volume", field=True, min=0, max=1, value=0.5,
                                               columnWidth3=(130, 50, 230))
        self.w["lead"] = cmds.floatSliderGrp(label="Avance (frames)", field=True, min=0, max=4, value=1.5,
                                             columnWidth3=(130, 50, 230), ann="La bouche precede le son")
        self.w["full"] = cmds.floatSliderGrp(label="Pleine forme a (frames)", field=True, min=2, max=12, value=5,
                                             columnWidth3=(130, 50, 230),
                                             ann="Un phoneme plus court que ca n'atteint pas son poids cible")
        self.w["tangent"] = cmds.optionMenuGrp(label="Tangentes", columnWidth2=(130, 150))
        for t in ("auto", "spline", "linear", "flat"):
            cmds.menuItem(label=t)
        cmds.setParent("..")

        cmds.frameLayout(label="Mapping Rhubarb -> charte (moteur rhubarb seulement)", collapsable=True, collapse=True,
                         marginWidth=4, marginHeight=4)
        saved = self.prefs.get("mapping", {})
        for shape in RHUBARB_SHAPES:
            default = saved.get(shape, core.DEFAULT_MAPPING.get(shape)) or "(aucun)"
            self.w["map_" + shape] = cmds.optionMenuGrp(label="%s  %s" % (shape, SHAPE_HELP[shape]),
                                                        columnWidth2=(230, 120))
            for c in MAP_CHOICES:
                cmds.menuItem(label=c)
            if default in MAP_CHOICES:
                cmds.optionMenuGrp(self.w["map_" + shape], e=True, value=default)
        cmds.setParent("..")

        cmds.separator(height=8, style="in")
        cmds.button(label="ANALYSER ET APPLIQUER", height=40, bgc=(0.3, 0.55, 0.3), c=lambda *_: self.run())
        cmds.rowLayout(numberOfColumns=2, adjustableColumn=1)
        cmds.button(label="Verifier la library", c=lambda *_: self.check_library())
        cmds.button(label="Effacer les cles lipsync", c=lambda *_: self.clear())
        cmds.setParent("..")
        self.w["log"] = cmds.scrollField(height=140, editable=False, wordWrap=True)
        cmds.setParent(col)
        cmds.showWindow(WINDOW)

    def _path_row(self, key, label, default, folder, filt=None):
        cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnAttach2=("both", "right"))
        self.w[key] = cmds.textFieldGrp(label=label, text=default, columnWidth2=(130, 250))
        cmds.button(label="...", width=30, c=lambda *_: self._browse(key, folder, filt))
        cmds.setParent("..")

    def _browse(self, key, folder, filt):
        mode = 3 if folder else 1
        res = cmds.fileDialog2(fileMode=mode, fileFilter=filt or "*", dialogStyle=2)
        if res:
            cmds.textFieldGrp(self.w[key], e=True, text=res[0])

    def val(self, key):
        return cmds.textFieldGrp(self.w[key], q=True, text=True).strip() if key != "recognizer" \
            else cmds.optionMenuGrp(self.w[key], q=True, value=True)

    def mapping(self):
        m = {}
        for shape in RHUBARB_SHAPES:
            v = cmds.optionMenuGrp(self.w["map_" + shape], q=True, value=True)
            if v != "(aucun)":
                m[shape] = v
        return m

    def log(self, text, clear=False):
        if clear:
            cmds.scrollField(self.w["log"], e=True, text="")
        cmds.scrollField(self.w["log"], e=True, insertText=text + "\n")

    # ---------------------------------------------------------------- actions
    def _from_scene(self):
        path, offset = maya_apply.scene_audio()
        if not path:
            self.log("Aucun son dans la scene.")
            return
        cmds.textFieldGrp(self.w["audio"], e=True, text=path)
        cmds.floatFieldGrp(self.w["start"], e=True, value1=offset)
        self.log("Audio du shot : %s (offset %g)" % (path, offset))

    def _library(self):
        return core.PoseLibrary(self.val("happy") or None, self.val("sad") or None)

    def check_library(self):
        self.log("", clear=True)
        try:
            lib = self._library()
        except Exception as exc:
            self.log("Erreur library : %s" % exc)
            return
        self.log("Visemes trouves : " + ", ".join(lib.visemes()))
        missing = [v for v in core.VISEMES if v != "Neutral" and not lib.available(v)]
        if missing:
            self.log("Absents : " + ", ".join(missing))
        ns = self.val("namespace") or None
        cache = {}
        not_found = [s for s in lib.controllers() if not maya_apply.resolve_controller(s, ns, cache)]
        self.log("%d controleurs dans les poses, %d introuvables dans la scene" % (len(lib.controllers()), len(not_found)))
        if not_found:
            self.log("  " + ", ".join(sorted(not_found)[:30]))

    def clear(self):
        try:
            lib = self._library()
        except Exception as exc:
            self.log("Erreur library : %s" % exc)
            return
        first = cmds.playbackOptions(q=True, min=True)
        last = cmds.playbackOptions(q=True, max=True)
        maya_apply.clear_keys(lib, first, last, self.val("namespace") or None)
        self.log("Cles effacees de %g a %g" % (first, last))

    def run(self):
        self._save_prefs()
        self.log("", clear=True)
        audio = self.val("audio") or None
        cues = self.val("cues") or None
        dialog = cmds.scrollField(self.w["dialog"], q=True, text=True)
        kw = dict(
            audio=audio,
            happy_folder=self.val("happy") or None,
            sad_folder=self.val("sad") or None,
            rhubarb_exe=self.val("rhubarb") or None,
            cues_json=cues,
            dialog_text=dialog,
            recognizer=self.val("recognizer"),
            engine="wav2vec2" if cmds.optionMenuGrp(self.w["engine"], q=True, value=True).startswith("wav2vec2") else "rhubarb",
            python_exe=self.val("python") or None,
            lang=self.val("lang") or "fr-fr",
            start_frame=cmds.floatFieldGrp(self.w["start"], q=True, value1=True),
            emotion=cmds.floatSliderGrp(self.w["emotion"], q=True, value=True),
            emotion_attr=self.val("emotion_attr") or None,
            namespace=self.val("namespace") or None,
            import_sound=cmds.checkBoxGrp(self.w["import"], q=True, value1=True),
            tangent=cmds.optionMenuGrp(self.w["tangent"], q=True, value=True),
            intensity=cmds.floatSliderGrp(self.w["intensity"], q=True, value=True),
            energy_influence=cmds.floatSliderGrp(self.w["energy"], q=True, value=True),
            lead_frames=cmds.floatSliderGrp(self.w["lead"], q=True, value=True),
            full_frames=cmds.floatSliderGrp(self.w["full"], q=True, value=True),
            mapping=self.mapping(),
        )
        cmds.undoInfo(openChunk=True)
        try:
            plan, nkeys, missing = maya_apply.run(**kw)
        except Exception as exc:
            self.log("ERREUR : %s" % exc)
            raise
        finally:
            cmds.undoInfo(closeChunk=True)
        self.log(core.plan_summary(plan))
        self.log("%d cles posees." % nkeys)
        if missing:
            self.log("Controleurs introuvables (ignores) : " + ", ".join(sorted(missing)))


def show():
    return LipsyncUI()
