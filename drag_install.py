# -*- coding: utf-8 -*-
"""Glisse ce fichier dans le viewport de Maya : il installe le tool et cree un bouton de shelf."""
import os
import shutil


def onMayaDroppedPythonFile(*args):
    from maya import cmds, mel
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maya_auto_lipsync")
    if not os.path.isdir(src):
        cmds.error("Dossier maya_auto_lipsync introuvable a cote de drag_install.py")
    scripts = cmds.internalVar(userScriptDir=True)
    dst = os.path.join(scripts, "maya_auto_lipsync")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    shelf = mel.eval("$tmp = $gShelfTopLevel")
    current = cmds.tabLayout(shelf, q=True, selectTab=True)
    for b in cmds.shelfLayout(current, q=True, childArray=True) or []:
        if cmds.shelfButton(b, q=True, exists=True) and cmds.shelfButton(b, q=True, label=True) == "Lipsync":
            cmds.deleteUI(b)
    cmds.shelfButton(parent=current, label="Lipsync", annotation="Auto Lipsync",
                     image="playblast.png", imageOverlayLabel="LIP", sourceType="python",
                     command="import importlib, maya_auto_lipsync\nimportlib.reload(maya_auto_lipsync)\nmaya_auto_lipsync.show()")
    cmds.confirmDialog(title="Auto Lipsync", button=["OK"],
                       message="Installe dans :\n%s\n\nUn bouton 'Lipsync' a ete ajoute a la shelf '%s'." % (dst, current))
    import maya_auto_lipsync
    maya_auto_lipsync.show()
