# Project Context — mkv-downmix v1.1

## Environment
- Language: Python 3
- Runtime: python3
- Build: N/A (script-based)
- Test: N/A (script-based, manual verification via ffprobe)
- Package Manager: N/A (no external Python deps)

## External Dependencies
- FFmpeg 8.1.2 (via Homebrew) — encoder AC3, E-AC3 disponibili
- Mount SMB: NAS-Dolomiti (21TB) su /Volumes/Download e /Volumes/Film

## Project Structure
```
/Users/bartolomeo/repos/mkv-downmix/
├── mkv-downmix.py       # Script principale (v1.1)
├── README.md            # Documentazione
├── .gitignore
├── .opencode/
│   ├── context.md       # Questo file
│   ├── todo.md          # Stato missione
│   └── plugins/
```

## Script Features (v1.1)
| Feature | Descrizione |
|---------|-------------|
| `--inplace` | Rinomina originale in OLD_<nome>, output con nome originale |
| `--upmix-stereo` | Upmix 2.0→5.1 via filtro surround FFmpeg |
| `--dry-run` | Mostra comandi senza eseguire |
| `--no-verify` | Salta verifica prerequisiti |
| `-o, --output` | Directory output personalizzata |
| **Progress bar** | Live con `\r` split, aggiornamento ogni ~1% |
| **MP4→MKV** | Input .mp4 convertiti in .mkv con stream copy video |

## Audio Handling
- 7.1 / Atmos / TrueHD / DTS-HD → AC3 5.1 640k (downmix)
- 5.1 → AC3 640k (compatibilità ottica Z906)
- 2.0 → copia (Z906 ha Pro Logic II hardware)
- FLAC, TrueHD, DTS, EAC3, AAC, PCM → tutti gestiti
- Solo tracce ITA/ENG mantenute

## Safety
- Video sempre stream copy (`-c:v copy`)
- Originali mai modificati (rinominati OLD_ in inplace)
- Error recovery: ripristino backup su fallimento
- Collision detection: skip se OLD_ già esiste

## GitHub
- Repo: github.com/bartolomeo902/mkv-downmix
- Branch: main
