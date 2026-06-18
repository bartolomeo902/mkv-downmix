#!/usr/bin/env python3
"""
mkv-downmix  v1.0
==================
Converte tracce audio 7.1 / DTS-HD / TrueHD / Atmos in AC3 5.1 640kbps
compatibile con Logitech Z906 collegato via cavo ottico (TOSLINK) alla TV.

Il video NON viene toccato (stream copy) — zero rischi di corruzione.

Utilizzo:
    python3 mkv-downmix.py ~/Downloads/TORRENT/        # tutta una cartella
    python3 mkv-downmix.py film.mkv                     # file singolo
    python3 mkv-downmix.py . --output ~/Movies/Z906/    # output personalizzato
    python3 mkv-downmix.py . --upmix-stereo             # upmix 2.0 → 5.1
    python3 mkv-downmix.py . --dry-run                  # mostra comandi senza eseguire
"""

import subprocess, json, os, sys, argparse, shutil, textwrap
from pathlib import Path

# Lingue da mantenere (sia ISO 639-1 che ISO 639-2)
KEEP_LANGS = {'ita', 'eng', 'en', 'it'}


def fmt_time(seconds):
    """Formatta secondi in HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:04.1f}"


def to_mkv(path):
    """Forza estensione .mkv (utile per input .mp4)."""
    return path.with_suffix('.mkv')


def run_ffmpeg(cmd, total_dur):
    """Esegue ffmpeg con barra di progresso live.

    Legge stderr in modalità binaria e splitta su \\r (come ffmpeg usa
    per le righe di progresso — non \\n come readline si aspetta).
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stderr_buf = b''
    stderr_chunks = []
    last_pct = -1

    while True:
        chunk = proc.stderr.read(4096)
        if not chunk:
            break
        stderr_buf += chunk

        # ffmpeg separa le righe di progresso con \\r, non \\n.
        # Splittiamo su \\r per estrarre ogni aggiornamento "time="
        while b'\r' in stderr_buf:
            raw_line, _, stderr_buf = stderr_buf.partition(b'\r')
            line = raw_line.decode('utf-8', errors='replace').strip()
            if not line:
                continue
            stderr_chunks.append(line)

            if total_dur > 0 and 'time=' in line:
                try:
                    # Estrae "HH:MM:SS.xx" dopo "time="
                    time_part = line.split('time=')[1].split()[0].strip()
                    h, m, s = time_part.split(':')
                    cur = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(cur / total_dur * 100, 100)
                    if int(pct) != last_pct:
                        bar_len = 20
                        filled = int(pct / 100 * bar_len)
                        bar = '█' * filled + '░' * (bar_len - filled)
                        print(
                            f"\r    [{bar}] {pct:.0f}%  "
                            f"({fmt_time(cur)} / {fmt_time(total_dur)})",
                            end='', file=sys.stderr,
                        )
                        sys.stderr.flush()
                        last_pct = pct
                except (ValueError, IndexError):
                    pass

    proc.wait()
    print(file=sys.stderr)  # nuova riga dopo la barra

    # Buffer residuo (eventuale \\n finale)
    if stderr_buf:
        rem = stderr_buf.decode('utf-8', errors='replace').strip()
        if rem:
            stderr_chunks.append(rem)

    stdout_output = ''
    if proc.stdout:
        stdout_output = proc.stdout.read().decode('utf-8', errors='replace')
        proc.stdout.close()

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=proc.returncode,
        stdout=stdout_output,
        stderr='\n'.join(stderr_chunks),
    )


# ─────────────────────────────────────────────
# 1. ANALISI FILE
# ─────────────────────────────────────────────

def probe(filepath):
    """Estrae tutti gli stream metadata con ffprobe."""
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_streams', '-show_format', str(filepath)],
        capture_output=True, text=True, timeout=120
    )
    return json.loads(r.stdout)


def norm_lang(lang):
    """Normalizza codici lingua ISO."""
    if not lang:
        return 'und'
    m = {'en': 'eng', 'it': 'ita', 'eng': 'eng', 'ita': 'ita'}
    return m.get(lang.lower(), lang.lower())


def classify_streams(data):
    """
    Classifica e filtra gli stream.
    Restituisce: (video, audio_selezionati, sub_selezionati)
    """
    streams = data.get('streams', [])
    all_audio = []
    all_subs = []
    video = []

    for s in streams:
        t = s['codec_type']
        lang = norm_lang(s.get('tags', {}).get('language', ''))
        entry = {
            'index': s['index'],
            'type': t,
            'codec': s.get('codec_name', ''),
            'language': lang,
            'channels': s.get('channels', 0),
            'channel_layout': s.get('channel_layout', ''),
            'tags': s.get('tags', {}),
        }

        if t == 'video':
            video.append(entry)
        elif t == 'audio':
            all_audio.append(entry)
        elif t == 'subtitle':
            all_subs.append(entry)

    # Filtra audio: solo italiano e inglese
    keep_audio = [a for a in all_audio if a['language'] in KEEP_LANGS]

    # Se non c'è italiano/inglese, tienile tutte (fallback)
    if not keep_audio:
        print("  ⚠️  Nessuna traccia ITA/ENG trovata — mantengo TUTTE le tracce audio")
        keep_audio = all_audio

    # Ordina: italiano prima, poi inglese
    def sort_key(a):
        lang_prio = 0 if a['language'] in ('ita', 'it') else 1
        return (lang_prio, a['index'])
    keep_audio.sort(key=sort_key)

    # Filtra sottotitoli: solo italiano e inglese
    keep_subs = [s for s in all_subs if s['language'] in KEEP_LANGS]

    return video, keep_audio, keep_subs


def describe_track(t):
    """Descrizione leggibile di una traccia audio."""
    ch = t['channels']
    suffix = f"{ch}.{max(0, ch-1)}" if ch > 0 else "?"
    codec = t['codec'].upper()
    lang = t['language'].upper()
    layout = t['channel_layout']
    return f"{lang} {suffix} {codec} ({layout})" if layout else f"{lang} {suffix} {codec}"


# ─────────────────────────────────────────────
# 2. COSTRUZIONE COMANDO FFMPEG
# ─────────────────────────────────────────────

def build_command(input_file, output_file, video, audio, subs, upmix):
    """Costruisce il comando ffmpeg con tutte le opzioni per-stream."""
    cmd = [
        'ffmpeg', '-i', str(input_file), '-y',
        '-map_metadata', '0',              # copia metadati globali + stream (auto)
    ]

    # ── Video: stream copy (zero rischi) ──
    if video:
        cmd += ['-map', f'0:{video[0]["index"]}', '-c:v', 'copy']
        print(f"    ✅ Video: {video[0]['codec']} copiato (nessuna modifica)")

    # ── Audio ──
    ao = 0  # output audio stream index
    for a in audio:
        cmd += ['-map', f'0:{a["index"]}']
        ch = a['channels']

        if ch >= 7:
            # 7.1 / Atmos / TrueHD → downmix a 5.1 AC3
            print(f"    🔄 [{ao}] {describe_track(a)} → AC3 5.1 640k (downmix 7.1→5.1)")
            cmd += [
                f'-c:a:{ao}', 'ac3',
                f'-b:a:{ao}', '640k',
                f'-ac:a:{ao}', '6',
            ]

        elif ch == 6:
            # 5.1 (DTS / DTS-HD / TrueHD / AC3) → AC3 per compatibilità Z906
            print(f"    🔄 [{ao}] {describe_track(a)} → AC3 640k")
            cmd += [
                f'-c:a:{ao}', 'ac3',
                f'-b:a:{ao}', '640k',
                f'-ac:a:{ao}', '6',
            ]

        elif ch <= 2 and ch > 0:
            if upmix:
                # 2.0 → AC3 5.1 con upmix surround
                print(f"    🔄 [{ao}] {describe_track(a)} → AC3 5.1 640k (upmix stereo→surround)")
                cmd += [
                    f'-c:a:{ao}', 'ac3',
                    f'-b:a:{ao}', '640k',
                    f'-ac:a:{ao}', '6',
                    f'-filter:a:{ao}', 'surround=chl_out=5.1',
                ]
            else:
                # 2.0 copiato così com'è: lo Z906 gestisce Pro Logic II
                print(f"    ✅ [{ao}] {describe_track(a)} copiato (Z906 → Pro Logic II)")
                cmd += [f'-c:a:{ao}', 'copy']

        else:
            # Fallback: copia
            print(f"    ✅ [{ao}] {describe_track(a)} copiato")
            cmd += [f'-c:a:{ao}', 'copy']

        ao += 1

    # ── Sottotitoli ──
    for s in subs:
        lang_label = s['language'].upper()
        codec = s['codec']
        cmd += ['-map', f'0:{s["index"]}']
        print(f"    ✅ Sottotitoli {lang_label} ({codec}) mantenuti")

    if subs:
        cmd += ['-c:s', 'copy']  # tutti i sub copiati

    # ── Output ──
    cmd.append(str(output_file))
    return cmd


# ─────────────────────────────────────────────
# 3. ESECUZIONE
# ─────────────────────────────────────────────

def process_file(filepath, output_dir, upmix, dry_run, inplace=False):
    """Elabora un singolo file MKV."""
    print(f"\n{'─'*60}")
    print(f"📦  {filepath.name}")
    print(f"{'─'*60}")

    # 1. Analisi
    try:
        data = probe(filepath)
    except subprocess.TimeoutExpired:
        print("  ❌ TIMEOUT: ffprobe non risponde")
        return False
    except Exception as e:
        print(f"  ❌ ERRORE probe: {e}")
        return False

    fmt = data.get('format', {}).get('format_name', '?')
    size_gb = filepath.stat().st_size / (1024**3)
    total_dur = float(data.get('format', {}).get('duration', 0))
    print(f"   Info: {fmt} | {size_gb:.1f} GB | {fmt_time(total_dur)}")

    # 2. Classifica
    video, audio, subs = classify_streams(data)
    total_audio = sum(1 for s in data.get('streams', []) if s['codec_type'] == 'audio')
    total_subs = sum(1 for s in data.get('streams', []) if s['codec_type'] == 'subtitle')

    print(f"   Video:     {len(video)} traccia(e)")
    print(f"   Audio:     {total_audio} trovate → {len(audio)} selezionate (ITA/ENG)")
    print(f"   Sub:       {total_subs} trovate → {len(subs)} selezionati (ITA/ENG)")

    if not audio:
        print("  ⚠️  Nessuna traccia audio selezionata, SKIP")
        return False

    # 3. Prepara output
    if inplace:
        # ── Modalità "in-place": l'output sostituisce l'originale ──
        backup_path = filepath.with_name(f"OLD_{filepath.name}")
        output_file = to_mkv(filepath)  # .mp4 → .mkv, .mkv resta .mkv

        if backup_path.exists() and not dry_run:
            print(f"\n  ⚠️  Backup già esistente: {backup_path.name}")
            print("     SKIP (per evitare sovrascrittura di un backup precedente)")
            return False

        input_for_ffmpeg = backup_path  # ffmpeg legge dal backup rinominato

        if not dry_run:
            print(f"\n   📦 Rinomino originale → {backup_path.name}")
            filepath.rename(backup_path)
        else:
            print(f"\n   🏁 DRY RUN: rinomino {filepath.name} → {backup_path.name}")
    else:
        # ── Modalità standard: output separato ──
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = to_mkv(output_dir / filepath.name)  # .mp4 → .mkv
        input_for_ffmpeg = filepath

        if output_file.exists() and not dry_run:
            print(f"\n  ⚠️  Output già esistente: {output_file.name}")
            resp = input("     Sovrascrivere? [s/N]: ").strip().lower()
            if resp != 's':
                print("     SKIP")
                return False

    # 4. Costruisci comando
    cmd = build_command(input_for_ffmpeg, output_file, video, audio, subs, upmix)

    if dry_run:
        print(f"\n   🏁 DRY RUN — comando:")
        cmd_str = ' \\\n      '.join(cmd)
        print(f"      {cmd_str}")
        return True

    # 5. Esegui con progress bar
    print(f"\n   ⏳ Conversione in corso...")
    sys.stdout.flush()

    try:
        r = run_ffmpeg(cmd, total_dur)

        if r.returncode != 0:
            print(f"  ❌ ERRORE (exit code {r.returncode})")
            err_lines = [l for l in r.stderr.split('\n') if l.strip()]
            for line in err_lines[-10:]:
                print(f"     {line}")
            # In inplace-mode, ripristina il backup
            if inplace and backup_path.exists() and not output_file.exists():
                print(f"\n   ↩️  Ripristino backup originale: {backup_path.name} → {filepath.name}")
                backup_path.rename(filepath)
            return False

        print(f"  ✅ COMPLETATO → {output_file}")

        # Statistiche: confronta col backup rinominato se inplace
        if inplace:
            in_size = backup_path.stat().st_size
        else:
            in_size = filepath.stat().st_size
        out_size = output_file.stat().st_size
        ratio = (out_size / in_size * 100) if in_size > 0 else 0
        print(f"     Dimensione: {out_size/1024/1024:.0f} MB ({ratio:.0f}% originale)")
        print(f"     Risparmio:  {(in_size - out_size)/1024/1024:.0f} MB")

        return True

    except subprocess.TimeoutExpired:
        print(f"  ❌ TIMEOUT (> 2 ore)")
        if inplace and backup_path.exists() and not output_file.exists():
            print(f"\n   ↩️  Ripristino backup originale: {backup_path.name} → {filepath.name}")
            backup_path.rename(filepath)
        return False
    except KeyboardInterrupt:
        print(f"\n  ⛔ Interrotto dall'utente")
        if inplace and backup_path.exists() and not output_file.exists():
            print(f"\n   ↩️  Ripristino backup originale: {backup_path.name} → {filepath.name}")
            backup_path.rename(filepath)
        return False
    except Exception as e:
        print(f"  ❌ ERRORE: {e}")
        if inplace and backup_path.exists() and not output_file.exists():
            print(f"\n   ↩️  Ripristino backup originale: {backup_path.name} → {filepath.name}")
            backup_path.rename(filepath)
        return False


# ─────────────────────────────────────────────
# 4. MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='mkv-downmix',
        description=textwrap.dedent("""\
            Converti tracce audio MKV per Logitech Z906 (cavo ottico).
            Il video viene copiato SENZA ricodifica — qualità originale preservata.""",
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Esempi:
              %(prog)s ~/Downloads/TORRENT/
              %(prog)s film.mkv
              %(prog)s . --output ~/Movies/Z906/ --upmix-stereo
              %(prog)s . --dry-run

            Dopo la conversione:
              TV (HDMI) → [cavo ottico TOSLINK] → Logitech Z906
              Imposta TV su "Bitstream" o "Pass-through" per audio HD
              Lo Z906 mostrerà "3D Dolby Digital" ✓
        """),
    )
    parser.add_argument('input', help='File MKV/MP4 o directory contenente MKV/MP4')
    parser.add_argument('-o', '--output', default=None,
                        help='Directory output (default: ./Z906-ready/ vicino all\'input)')
    parser.add_argument('--upmix-stereo', action='store_true',
                        help='Upmix stereo 2.0 → 5.1 surround (default: lascia stereo, Z906 fa Pro Logic II)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Mostra i comandi senza eseguirli')
    parser.add_argument('--no-verify', action='store_true',
                        help='Salta verifica prerequisiti')
    parser.add_argument('--inplace', action='store_true',
                        help='Rinomina originale in OLD_<nome> e salva il convertito con il nome originale')

    args = parser.parse_args()

    # ── Verifica prerequisiti ──
    if not args.dry_run and not args.no_verify:
        if not shutil.which('ffmpeg'):
            print("❌ ffmpeg non trovato. Installa con:  brew install ffmpeg")
            sys.exit(1)

        # Verifica encoder AC3
        r = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True)
        if 'ac3' not in r.stdout:
            print("❌ Encoder AC3 non disponibile in ffmpeg.")
            print("   Reinstalla con: brew reinstall ffmpeg --with-libfdk-aac")
            sys.exit(1)

        print("✅ ffmpeg " + subprocess.run(
            ['ffmpeg', '-version'], capture_output=True, text=True
        ).stdout.split('\n')[0].split()[2] + " + encoder AC3 disponibili\n")

    # ── Input ──
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"❌ Input non trovato: {input_path}")
        sys.exit(1)

    if input_path.is_file():
        files = [input_path]
    else:
        files = sorted(input_path.glob('*.mkv'))
        files += sorted(f for f in input_path.glob('*.mka') if f not in files)
        files += sorted(f for f in input_path.glob('*.mp4') if f not in files)

    if not files:
        print(f"❌ Nessun file MKV/MKA/MP4 trovato in: {input_path}")
        sys.exit(1)

    # ── Config ──
    print(f"Trovati {len(files)} file da processare\n")
    print("═" * 60)
    print("CONFIGURAZIONE:")
    print(f"  Input:        {input_path}")
    print(f"  File:         {len(files)}")
    print(f"  Upmix stereo: {'SÌ (surround simulato)' if args.upmix_stereo else 'NO (Z906 fa Pro Logic II)'}")
    print(f"  Dry run:      {'SÌ' if args.dry_run else 'NO'}")
    print(f"  In-place:     {'SÌ (originale → OLD_<nome>)' if args.inplace else 'NO (output separato)'}")
    print("═" * 60)

    # ── Output directory ──
    if args.inplace:
        # Modalità in-place: output nella stessa cartella dell'input
        output_dir = None
        if not args.dry_run:
            print(f"\n📂 Output: in-place (originali rinominati OLD_<nome>)")
    else:
        if args.output:
            output_dir = Path(args.output).expanduser().resolve()
        else:
            if input_path.is_dir():
                output_dir = input_path / 'Z906-ready'
            else:
                output_dir = input_path.parent / 'Z906-ready'

        if not args.dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            print(f"\n📂 Output: {output_dir}")

    # ── Processa ──
    ok = fail = 0
    for f in files:
        if process_file(f, output_dir, args.upmix_stereo, args.dry_run, args.inplace):
            ok += 1
        else:
            fail += 1

    # ── Riepilogo ──
    print(f"\n{'═'*60}")
    print(f"RIEPILOGO: {ok}/{ok+fail} completati")
    if fail > 0:
        print(f"❌ {fail} fallito(i)")
    if ok > 0 and not args.dry_run:
        if args.inplace:
            print(f"\n📂 Output: in-place (originali in OLD_<nome>)")
        else:
            print(f"\n📂 Output: {output_dir}")
        print(f"\n💡 Dopo la conversione:")
        print(f"   1. Collega TV → Z906 via cavo ottico (TOSLINK)")
        print(f"   2. Imposta l'uscita audio TV su \"Bitstream\" o \"Pass-through\"")
        print(f"   3. Lo Z906 mostrerà \"3D Dolby Digital\" ✓")
    print(f"{'═'*60}")


if __name__ == '__main__':
    main()
