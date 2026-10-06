# Maya Auto Lipsync

Tool Maya qui analyse l'audio d'un shot, en sort les phonèmes et pose des clés
blendées à partir des poses Studio Library de ta charte (PHONEM HAPPY / PHONEM SAD).

Deux moteurs de phonèmes au choix :

| Moteur | Qualité | Installation |
|---|---|---|
| **wav2vec2** (recommandé) | vrais phonèmes IPA, multilingue, toute la charte est utilisée (`Ch`, `Ai`, `i`, `SZTDN`...) | un Python à part avec torch, ~2 Go |
| rhubarb | 9 formes de bouche seulement, pensé pour l'anglais | un zip |

Aucune pose n'est appliquée à 100 % (sauf les fermetures MBP) : chaque pose est
convertie en delta par rapport à `Neutral`, et chaque clé est
`neutral + poids * (emotion * delta_happy + (1 - emotion) * delta_sad)`.
Entre deux clés Maya interpole, ce qui donne le crossfade de coarticulation.

## Installation

1. Télécharge le repo (bouton `Code` → `Download ZIP` sur GitHub) et dézippe-le
   n'importe où. Glisse `drag_install.py` dans le viewport de Maya : le dossier
   est copié dans tes scripts Maya et un bouton `Lipsync` apparaît sur la shelf.
   À la main sinon : copie le dossier `maya_auto_lipsync` dans
   `Documents/maya/scripts` (ou `Documents/maya/<version>/scripts`).
2. Installe un moteur de phonèmes (voir ci-dessous).
3. Dans Maya (Script Editor, onglet Python) :

```python
import maya_auto_lipsync
maya_auto_lipsync.show()
```

Tu peux mettre ces deux lignes sur un bouton de shelf.

## Moteur wav2vec2 (recommandé)

Le modèle tourne hors de Maya, dans un Python classique (3.9 à 3.12), parce
qu'il a besoin de torch. Une seule fois :

1. Installe Python depuis https://www.python.org (coche "Add to PATH").
2. Dans un terminal :

```
python -m venv C:\tools\lipsync_env
C:\tools\lipsync_env\Scripts\pip install torch transformers soundfile numpy
```

   Sur Mac / Linux : `python3 -m venv ~/lipsync_env && ~/lipsync_env/bin/pip install torch transformers soundfile numpy`.
3. Dans le tool, champ `Executable python`, pointe sur
   `C:\tools\lipsync_env\Scripts\python.exe` (ou `~/lipsync_env/bin/python`).

Au premier lancement le modèle (environ 1,2 Go) est téléchargé puis mis en cache.
Les lancements suivants prennent quelques secondes.

**Alignement sur le texte** : si tu colles le texte de la réplique, l'audio est
aligné dessus et le timing est nettement plus fiable. Il faut en plus
`pip install phonemizer torchaudio` et [espeak-ng](https://github.com/espeak-ng/espeak-ng/releases)
installé sur la machine. Sans ça, le tool retombe sur la reconnaissance libre.

Tu peux aussi lancer le moteur à la main et donner le JSON au tool :

```
python maya_auto_lipsync/phonemes_wav2vec.py dialog.wav -o cues.json --text "Bonjour" --lang fr-fr
```

La table phonème → pose est dans `phonemes_wav2vec.py` (`IPA_MAP`), modifiable.

## Moteur rhubarb

Télécharge [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync/releases)
(un zip, pas d'install) et pointe le champ `Executable rhubarb` sur `rhubarb.exe`.
Recognizer `phonetic` pour le français, `pocketSphinx` pour l'anglais. Le panneau
Mapping règle la correspondance entre ses 9 formes et tes poses.

## Utilisation

1. **Library** : donne le dossier `PHONEM HAPPY` et le dossier `PHONEM SAD`
   (les dossiers qui contiennent les `h_*.pose` et `s_*.pose`). Si ton rig est
   référencé, mets son namespace. `Vérifier la library` liste les visèmes
   trouvés et les contrôleurs introuvables dans la scène.
2. **Audio** : un `.wav` (Rhubarb ne lit pas le mp3), ou
   `Prendre le son du shot` qui récupère le son du time slider et son offset.
   Le texte du dialogue est optionnel mais améliore nettement la détection.
3. **Moteur** : wav2vec2 ou rhubarb, avec le chemin de son exécutable.
   Tu peux aussi donner directement un JSON déjà calculé.
4. **Blending** :
   - `Emotion` : 0 = jeu SAD, 1 = jeu HAPPY, entre les deux = mélange. Pour
     changer d'émotion au cours du plan, donne un attribut animé
     (`face_ctrl.happy`) dans `Attribut emotion animé`.
   - `Intensité` : multiplicateur global des poids (les MBP restent à 100 %).
   - `Influence du volume` : les voyelles s'ouvrent plus quand l'audio est fort.
   - `Avance` : la bouche précède le son de N frames (1 à 2 en général).
   - `Pleine forme à` : un phonème plus court que ça n'atteint pas sa cible,
     ce qui écrase naturellement les formes dans les passages rapides.
5. **Mapping** (rhubarb seulement) : correspondance formes Rhubarb → poses.
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
- `maya_auto_lipsync/phonemes_wav2vec.py` : moteur de phonèmes, lancé dans un
  Python externe. Table IPA → poses de la charte.
- `maya_auto_lipsync/maya_apply.py` : résolution des contrôleurs, clés, audio.
- `maya_auto_lipsync/ui.py` : la fenêtre.
- `tests/test_core.py` : tests du cœur, `python tests/test_core.py`.

## Limites connues

- Avec rhubarb, les poses `Ch` et `Ai` ne sont pas utilisées par défaut (il ne
  distingue pas ces sons). Le moteur wav2vec2 n'a pas cette limite.
- Les deux jeux de poses doivent avoir été sauvés sur les mêmes contrôleurs.
  Un contrôleur absent d'un jeu est traité comme neutre dans ce jeu.
