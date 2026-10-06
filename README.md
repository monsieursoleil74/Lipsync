# Maya Auto Lipsync

Tool Maya qui analyse l'audio d'un shot, en sort les phonèmes et pose des clés
blendées à partir des poses Studio Library de ta charte (PHONEM HAPPY / PHONEM SAD).

Aucune pose n'est appliquée à 100 % (sauf les fermetures MBP) : chaque pose est
convertie en delta par rapport à `Neutral`, et chaque clé est
`neutral + poids * (emotion * delta_happy + (1 - emotion) * delta_sad)`.
Entre deux clés Maya interpole, ce qui donne le crossfade de coarticulation.

## Installation

1. Copie le dossier `maya_auto_lipsync` dans ton dossier de scripts Maya
   (`Documents/maya/scripts` ou `Documents/maya/<version>/scripts`).
2. Installe [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync/releases)
   (un zip, pas d'install). Note le chemin de l'exécutable `rhubarb` / `rhubarb.exe`.
3. Dans Maya (Script Editor, onglet Python) :

```python
import maya_auto_lipsync
maya_auto_lipsync.show()
```

Tu peux mettre ces deux lignes sur un bouton de shelf.

## Utilisation

1. **Library** : donne le dossier `PHONEM HAPPY` et le dossier `PHONEM SAD`
   (les dossiers qui contiennent les `h_*.pose` et `s_*.pose`). Si ton rig est
   référencé, mets son namespace. `Vérifier la library` liste les visèmes
   trouvés et les contrôleurs introuvables dans la scène.
2. **Audio** : un `.wav` (Rhubarb ne lit pas le mp3), ou
   `Prendre le son du shot` qui récupère le son du time slider et son offset.
   Le texte du dialogue est optionnel mais améliore nettement la détection.
3. **Rhubarb** : chemin de l'exécutable. Recognizer `phonetic` pour le
   français (ou toute langue), `pocketSphinx` seulement pour de l'anglais.
   Tu peux aussi donner directement un JSON Rhubarb déjà calculé.
4. **Blending** :
   - `Emotion` : 0 = jeu SAD, 1 = jeu HAPPY, entre les deux = mélange. Pour
     changer d'émotion au cours du plan, donne un attribut animé
     (`face_ctrl.happy`) dans `Attribut emotion animé`.
   - `Intensité` : multiplicateur global des poids (les MBP restent à 100 %).
   - `Influence du volume` : les voyelles s'ouvrent plus quand l'audio est fort.
   - `Avance` : la bouche précède le son de N frames (1 à 2 en général).
   - `Pleine forme à` : un phonème plus court que ça n'atteint pas sa cible,
     ce qui écrase naturellement les formes dans les passages rapides.
5. **Mapping** : correspondance formes Rhubarb → poses de la charte, modifiable.
   Les variantes `(a)` / `(o)` de MBP, SZTDN et V F sont choisies
   automatiquement selon la voyelle voisine (ronde → `(o)`, ouverte → `(a)`).
6. `ANALYSER ET APPLIQUER`. Tout est dans un seul undo. Les anciennes clés
   des contrôleurs de la bouche sont remplacées sur la plage de l'audio.

### Comment sont posées les clés

- Une clé au centre de chaque phonème. Pour les phonèmes longs, deux clés de
  tenue (début + 2 frames, fin - 2 frames).
- Poids d'une clé = cible du visème × facteur de durée × facteur de volume
  (voyelles seulement) × intensité. Les cibles sont dans `core.TARGET_WEIGHTS`.
- Tangentes `auto` par défaut (pas d'overshoot). Les courbes restent éditables
  dans le Graph Editor comme n'importe quelle anim.

### Sans interface

```python
import maya_auto_lipsync
plan, nkeys, missing = maya_auto_lipsync.run(
    audio="D:/shots/sh010/dialog.wav",
    happy_folder="D:/library/PHONEM HAPPY",
    sad_folder="D:/library/PHONEM SAD",
    rhubarb_exe="D:/tools/rhubarb/rhubarb.exe",
    dialog_text="Bonjour, comment ça va ?",
    namespace="hero",
    emotion=0.8,
    start_frame=1001,
)
```

## Structure

- `maya_auto_lipsync/core.py` : lecture des poses, Rhubarb, énergie audio,
  planification des clés. Aucune dépendance à Maya.
- `maya_auto_lipsync/maya_apply.py` : résolution des contrôleurs, clés, audio.
- `maya_auto_lipsync/ui.py` : la fenêtre.
- `tests/test_core.py` : tests du cœur, `python tests/test_core.py`.

## Limites connues

- Rhubarb sort des visèmes (formes de bouche), pas des phonèmes exacts : les
  poses `Ch` et `Ai` ne sont pas utilisées par défaut, tu peux les mapper à la
  main (par exemple `H → Ai`).
- Les deux jeux de poses doivent avoir été sauvés sur les mêmes contrôleurs.
  Un contrôleur absent d'un jeu est traité comme neutre dans ce jeu.
