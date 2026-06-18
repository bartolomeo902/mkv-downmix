# mkv-downmix

Converte tracce audio **7.1 / Atmos / TrueHD / DTS-HD / DTS:X** da file MKV in **AC3 5.1 640 kbps** compatibile con **Logitech Z906** collegato via **cavo ottico TOSLINK** alla TV.

Il **video non viene toccato** (stream copy) — zero rischi di corruzione o perdita di qualità.

## Perché

Il Logitech Z906 via cavo ottico (TOSLINK) supporta:
- **Dolby Digital (AC3)** 5.1 fino a 640 kbps ✅
- **DTS** 5.1 (ma molte TV bloccano il passthrough DTS)
- **PCM stereo** (per il Pro Logic II integrato dello Z906)

**Non supporta** via ottico: 7.1, Dolby TrueHD, DTS-HD MA, Atmos, PCM multicanale.

Questo script converte selettivamente solo l'audio, preservando video e sottotitoli.

## Installazione

**Prerequisiti:** [FFmpeg](https://ffmpeg.org/) (versione 5+)

```bash
# macOS (Homebrew)
brew install ffmpeg

# Linux (apt)
sudo apt install ffmpeg

# Verifica
ffmpeg -version
ffmpeg -encoders | grep ac3    # deve mostrare l'encoder AC3
```

## Utilizzo

```bash
python3 mkv-downmix.py ~/Downloads/TORRENT/

# Opzioni
python3 mkv-downmix.py film.mkv                          # file singolo
python3 mkv-downmix.py . -o ~/Movies/Z906/                # output personalizzato
python3 mkv-downmix.py . --upmix-stereo                    # upmix 2.0 → 5.1
python3 mkv-downmix.py . --dry-run                         # mostra comandi senza eseguire
```

## Cosa fa

| Passaggio | Azione |
|-----------|--------|
| **1** | Cicla tutti i `.mkv` nella directory |
| **2** | Analizza ogni file con `ffprobe` (video, audio, sub) |
| **3** | **Rimuove** tracce audio e sub non ITA/ENG |
| **4** | **7.1 → AC3 5.1** 640k (downmix) |
| **5** | **5.1 → AC3** 640k (per compatibilità ottica) |
| **6** | **2.0** → copia così com'è (Z906 fa Pro Logic II) |
| **7** | **Video**: stream copy — identico |
| **8** | **Sub**: copiati, solo ITA/ENG |
| **9** | Output in `./Z906-ready/` |

## Perché non upmixare lo stereo via software

Lo Z906 ha **Dolby Pro Logic II hardware** — processa lo stereo in 5.1 in tempo reale
meglio di qualsiasi filtro software. Se preferisci l'upmix via FFmpeg, usa `--upmix-stereo`.

## Configurazione TV

Dopo la conversione:
1. TV (HDMI) → **cavo ottico TOSLINK** → Logitech Z906
2. Imposta uscita audio TV su **"Bitstream"** o **"Pass-through"**
3. Lo Z906 mostrerà **"3D Dolby Digital"** quando riconosce il 5.1

## Test

```bash
# Crea un file di test con 7.1 + stereo
ffmpeg -y \
  -f lavfi -i "testsrc2=duration=15:size=1280x720:rate=24" \
  -f lavfi -i "anullsrc=r=48000:cl=7.1:duration=15" \
  -f lavfi -i "anullsrc=r=48000:cl=stereo:duration=15" \
  -map 0:v \
  -map 1:a -metadata:s:a:0 language=ita \
  -map 2:a -metadata:s:a:1 language=eng \
  -c:v libx264 -c:a copy test-7.1.mkv

# Converti
python3 mkv-downmix.py test-7.1.mkv --dry-run
python3 mkv-downmix.py test-7.1.mkv

# Verifica
ffprobe Z906-ready/test-7.1.mkv
```
