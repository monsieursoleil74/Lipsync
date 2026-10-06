# -*- coding: utf-8 -*-
"""Auto lipsync pour Maya a partir de poses Studio Library et de Rhubarb Lip Sync.

Usage dans Maya :
    import maya_auto_lipsync
    maya_auto_lipsync.show()
"""
__version__ = "0.1.0"


def show():
    from . import ui
    return ui.show()


def run(**kw):
    from . import maya_apply
    return maya_apply.run(**kw)
