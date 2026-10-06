# -*- coding: utf-8 -*-
"""
Moteur de phonemes base sur wav2vec2 (multilingue, francais inclus).

A lancer HORS de Maya, dans un Python ou torch + transformers sont installes :

    pip install torch transformers soundfile numpy
    python phonemes_wav2vec.py dialog.wav -o cues.json
    python phonemes_wav2vec.py dialog.wav -o cues.json --text "Bonjour, comment ca va ?" --lang fr-fr

Avec --text, l'audio est aligne sur le texte (forced alignment), ce qui est
plus precis. Il faut alors en plus :  pip install phonemizer   et espeak-ng.
Sans --text, le modele reconnait librement les phonemes.

Sortie : un JSON lisible par le tool Maya, avec pour chaque phoneme
{start, end, value: ipa, viseme: pose de la charte, kind: open|round|consonant|closure|rest}.
"""
import argparse
import json
import os
import sys
import unicodedata

MODEL = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"
SAMPLE_RATE = 16000

# IPA -> (viseme de la charte, classe). Les cles longues sont testees en premier.
IPA_MAP = {
    # fermetures
    "p": ("MBP", "closure"), "b": ("MBP", "closure"), "m": ("MBP", "closure"),
    # labiodentales
    "f": ("VF", "consonant"), "v": ("VF", "consonant"),
    # chuintantes
    "ʃ": ("Ch", "consonant"), "ʒ": ("Ch", "consonant"), "tʃ": ("Ch", "consonant"), "dʒ": ("Ch", "consonant"),
    # dentales / alveolaires / velaires -> dents visibles
    "s": ("SZTDN", "consonant"), "z": ("SZTDN", "consonant"), "t": ("SZTDN", "consonant"),
    "d": ("SZTDN", "consonant"), "n": ("SZTDN", "consonant"), "l": ("SZTDN", "consonant"),
    "k": ("SZTDN", "consonant"), "g": ("SZTDN", "consonant"), "ɡ": ("SZTDN", "consonant"),
    "ŋ": ("SZTDN", "consonant"), "ɲ": ("SZTDN", "consonant"), "ʁ": ("SZTDN", "consonant"),
    "r": ("SZTDN", "consonant"), "ɹ": ("SZTDN", "consonant"), "x": ("SZTDN", "consonant"),
    "θ": ("SZTDN", "consonant"), "ð": ("SZTDN", "consonant"), "ts": ("SZTDN", "consonant"),
    "j": ("i", "open"), "h": (None, None), "ʔ": (None, None),
    # semi-voyelles arrondies
    "w": ("OuUOn", "round"), "ɥ": ("OuUOn", "round"),
    # voyelles ouvertes
    "a": ("A", "open"), "ɑ": ("Ah", "open"), "æ": ("A", "open"), "ʌ": ("A", "open"), "ɐ": ("A", "open"),
    "ɛ": ("E", "open"), "e": ("E", "open"), "ɜ": ("E", "open"), "ɚ": ("E", "open"), "ɝ": ("E", "open"),
    "i": ("i", "open"), "ɪ": ("i", "open"), "y": ("OoEn", "round"),
    "aɪ": ("Ai", "open"), "eɪ": ("Ai", "open"), "aj": ("Ai", "open"), "ɔɪ": ("Ai", "open"),
    "aʊ": ("A", "open"), "oʊ": ("OoEn", "round"), "əʊ": ("OoEn", "round"),
    # voyelles arrondies
    "o": ("OoEn", "round"), "ɔ": ("OoEn", "round"), "ø": ("OoEn", "round"), "œ": ("OoEn", "round"),
    "ə": ("OoEn", "round"), "u": ("OuUOn", "round"), "ʊ": ("OuUOn", "round"),
}
_STRIP = "̃ːˈˌ̯̩͜͡"   # tilde nasal, longueur, accents, liaisons


def normalize_ipa(token):
    token = unicodedata.normalize("NFD", token)
    return "".join(c for c in token if c not in _STRIP)


def ipa_to_viseme(token):
    """Renvoie (viseme, kind) ou (None, None) si le phone n'a pas d'impact visuel."""
    t = normalize_ipa(token)
    if not t or t in ("|", " ", "<pad>", "<s>", "</s>", "<unk>"):
        return ("Neutral", "rest") if t in ("|", " ") else (None, None)
    if t in IPA_MAP:
        return IPA_MAP[t]
    # token compose : plus long prefixe connu
    for n in range(len(t), 0, -1):
        if t[:n] in IPA_MAP:
            return IPA_MAP[t[:n]]
    return (None, None)


def segments_to_cues(segments, duration, max_gap=0.12, min_rest=0.08):
    """[(start, end, ipa)] -> cues avec repos dans les silences et durees etendues jusqu'au phone suivant."""
    phones = []
    for start, end, ipa in segments:
        vis, kind = ipa_to_viseme(ipa)
        if vis is None:
            continue
        if kind == "rest":
            continue  # les silences sont deduits des trous
        phones.append([float(start), float(end), ipa, vis, kind])
    cues = []
    t = 0.0
    for i, (start, end, ipa, vis, kind) in enumerate(phones):
        nxt = phones[i + 1][0] if i + 1 < len(phones) else duration
        if start - t >= min_rest:
            cues.append({"start": round(t, 4), "end": round(start, 4), "value": "sil", "viseme": "Neutral", "kind": "rest"})
        real_end = nxt if nxt - end <= max_gap else end
        real_end = max(real_end, start + 0.02)
        cues.append({"start": round(start, 4), "end": round(real_end, 4), "value": ipa, "viseme": vis, "kind": kind})
        t = real_end
    if duration - t >= min_rest:
        cues.append({"start": round(t, 4), "end": round(duration, 4), "value": "sil", "viseme": "Neutral", "kind": "rest"})
    return cues


# ---------------------------------------------------------------------------

def load_audio(path):
    import numpy as np
    import soundfile as sf
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    data = data.mean(axis=1)
    if rate != SAMPLE_RATE:
        n = int(len(data) * SAMPLE_RATE / float(rate))
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype("float32")
    return data, len(data) / float(SAMPLE_RATE)


def recognize(audio, model_name=MODEL, text=None, lang="fr-fr"):
    import torch
    from transformers import AutoProcessor, AutoModelForCTC
    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModelForCTC.from_pretrained(model_name).eval()
    inputs = processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
    with torch.no_grad():
        logits = model(inputs.input_values).logits[0]
    frame_sec = model.config.inputs_to_logits_ratio / float(SAMPLE_RATE)

    if text:
        try:
            return forced_align(logits, processor, text, lang, frame_sec)
        except Exception as exc:  # phonemizer absent, espeak absent...
            sys.stderr.write("Alignement sur le texte impossible (%s), reconnaissance libre.\n" % exc)

    ids = torch.argmax(logits, dim=-1)
    decoded = processor.batch_decode(ids.unsqueeze(0), output_char_offsets=True)
    offsets = decoded.char_offsets[0]
    segments = []
    for o in offsets:
        segments.append((o["start_offset"] * frame_sec, o["end_offset"] * frame_sec, o["char"]))
    return segments


def forced_align(logits, processor, text, lang, frame_sec):
    import torch
    import torchaudio.functional as F
    from phonemizer import phonemize
    ipa = phonemize(text, language=lang, backend="espeak", strip=True, with_stress=False)
    tokenizer = processor.tokenizer
    tokens = [t for t in tokenizer.tokenize(ipa) if t in tokenizer.get_vocab()]
    ids = torch.tensor([[tokenizer.convert_tokens_to_ids(t) for t in tokens]], dtype=torch.int32)
    log_probs = torch.log_softmax(logits, dim=-1).unsqueeze(0)
    blank = tokenizer.pad_token_id
    alignment, _ = F.forced_align(log_probs, ids, blank=blank)
    spans = F.merge_tokens(alignment[0], torch.ones_like(alignment[0], dtype=torch.float), blank=blank)
    segments = []
    for span in spans:
        tok = tokenizer.convert_ids_to_tokens(int(span.token))
        segments.append((span.start * frame_sec, span.end * frame_sec, tok))
    return segments


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--text", default=None, help="texte du dialogue (alignement force)")
    ap.add_argument("--text-file", default=None)
    ap.add_argument("--lang", default="fr-fr", help="langue espeak pour --text (fr-fr, en-us...)")
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args(argv)

    text = args.text
    if args.text_file and os.path.isfile(args.text_file):
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()

    audio, duration = load_audio(args.audio)
    segments = recognize(audio, args.model, text, args.lang)
    cues = segments_to_cues(segments, duration)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"soundFile": args.audio, "duration": duration, "engine": "wav2vec2",
                                "model": args.model}, "mouthCues": cues}, f, ensure_ascii=False, indent=1)
    sys.stdout.write("%d phonemes -> %s\n" % (len(cues), args.output))


if __name__ == "__main__":
    main()
