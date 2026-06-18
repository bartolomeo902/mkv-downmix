# Mission: Convertire MKV per Logitech Z906 — COMPLETATA

## Stato: ✅ Completata
Lo script è pronto, testato e pushato su GitHub. L'utente esegue la conversione in autonomia.

## Riepilogo modifiche apportate

### v1.0 → v1.1 (modifiche cumulative)
- [x] **Progress bar live** — stderr letto in binario, split su `\r` (ffmpeg usa carriage return, non newline)
- [x] **ffprobe timeout**: 60s → 120s (per REMUX via SMB)
- [x] **Supporto MP4 → MKV** — input `.mp4` convertiti in `.mkv`, video stream copy, estensione output `.mkv`
- [x] **Flag `--inplace`** — rinomina originale in `OLD_<nome>`, scrive convertito con nome originale
- [x] **Error recovery** — se conversione fallisce in inplace, ripristina backup
- [x] **Collision detection** — se `OLD_<nome>` esiste già, skip

### Test effettuati
- [x] Test 7.1 ITA + stereo ENG → downmix OK, stereo copy OK
- [x] Test FLAC 7.1 → AC3 5.1 640k (funziona)
- [x] Test American Psycho (55GB, SMB) → completato in 17 min
- [x] Test MP4→MKV con `--inplace` → OK
- [x] Test progress bar su file 3.2GB → OK (aggiornamenti ogni ~1%)
- [x] Test collision detection OLD_ → OK (skip se backup esiste)

### Comando per l'utente
```bash
python3 mkv-downmix.py "/Volumes/Film/Film/" --inplace
```
