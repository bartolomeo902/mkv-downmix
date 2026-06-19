#!/usr/bin/env python3
"""
mkv-downmix  v1.2
==================
Converte tracce audio 7.1 / DTS-HD / TrueHD / Atmos in AC3 5.1 640kbps
compatibile con Logitech Z906 collegato via cavo ottico (TOSLINK) alla TV.

Il video NON viene toccato (stream copy) — zero rischi di corruzione.

Novità v1.2:
  - Skip intelligente: salta file già Z906-compatibili
  - Filter backup: ignora i file già processati (Z906_BAK_*, OLD_*)
  - Nuovo prefisso backup: Z906_BAK_ (era OLD_)
  - Rollback corretto su Ctrl+C: elimina output parziale + ripristina originale
  - Verifica output con ffprobe dopo la conversione
  - Check spazio libero prima di iniziare
  - Log persistente (mkv-downmix.log accanto allo script)
  - Pre-scan + riepilogo prima di partire (anche in --dry-run)
  - Conferma globale per batch ≥ 5 file o ≥ 20 GB

Utilizzo:
    python3 mkv-downmix.py ~/Downloads/TORRENT/         # tutta una cartella
    python3 mkv-downmix.py film.mkv                      # file singolo
    python3 mkv-downmix.py . --output ~/Movies/Z906/     # output personalizzato
    python3 mkv-downmix.py . --upmix-stereo              # upmix 2.0 → 5.1
    python3 mkv-downmix.py . --dry-run                   # mostra cosa farebbe
    python3 mkv-downmix.py . --inplace                   # rinomina e sostituisci
    python3 mkv-downmix.py . --force                     # converti anche se già OK
    python3 mkv-downmix.py . --yes                       # salta conferma globale
"""

import subprocess, json, os, sys, argparse, shutil, textwrap, time
from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────────────
# COSTANTI
# ─────────────────────────────────────────────

# Lingue da mantenere (sia ISO 639-1 che ISO 639-2)
KEEP_LANGS = {'ita', 'eng', 'en', 'it'}

# Naming dei backup
BACKUP_PREFIX = 'Z906_BAK_'
LEGACY_PREFIXES = ('OLD_',)  # filtra anche i vecchi backup

# Log persistente accanto allo script
LOG_PATH = Path(__file__).resolve().parent / 'mkv-downmix.log'

# Soglie per conferma globale (chiede "Procedere?" se superate)
CONFIRM_FILE_THRESHOLD = 5
CONFIRM_SIZE_GB = 20.0

# Margine di sicurezza per spazio disco (1.2× = 20% margine)
DISK_SAFETY_FACTOR = 1.2

# Tolleranza durata in verifica output (1% di scarto accettato)
DURATION_TOLERANCE = 0.99


# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────

def fmt_time(seconds):
    """Formatta secondi in HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:04.1f}"


def fmt_size(bytes_):
    """Formatta bytes in GB/MB."""
    gb = bytes_ / (1024**3)
    if gb >= 1.0:
        return f"{gb:.1f} GB"
    mb = bytes_ / (1024**2)
    if mb >= 10:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB"


def to_mkv(path):
    """Forza estensione .mkv (utile per input .mp4)."""
    return path.with_suffix('.mkv')


def is_backup(name):
    """True se il file è un backup di una conversione precedente."""
    return name.startswith(BACKUP_PREFIX) or any(
        name.startswith(p) for p in LEGACY_PREFIXES
    )


def log_event(level, name, message=''):
    """Scrive una riga nel log persistente. Non fallisce mai."""
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f'{ts}  {level:5}  {name}  {message}\n')
    except OSError:
        pass  # log failure non è fatale


def norm_lang(lang):
    """Normalizza codici lingua ISO."""
    if not lang:
        return 'und'
    m = {'en': 'eng', 'it': 'ita', 'eng': 'eng', 'ita': 'ita'}
    return m.get(lang.lower(), lang.lower())


# ─────────────────────────────────────────────
# 1. ANALISI FILE (ffprobe)
# ─────────────────────────────────────────────

def probe(filepath):
    """Estrae tutti gli stream metadata con ffprobe."""
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_streams', '-show_format', str(filepath)],
        capture_output=True, text=True, timeout=120,
    )
    return json.loads(r.stdout)


def classify_streams(data):
    """
    Classifica e filtra gli stream.
    Restituisce: (video, audio_selezionati, sub_selezionati, info)
    info è un dict con: total_audio, total_subs, fallback_used.
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

    keep_audio = [a for a in all_audio if a['language'] in KEEP_LANGS]
    fallback_used = False
    if not keep_audio:
        keep_audio = all_audio
        fallback_used = True

    def sort_key(a):
        lang_prio = 0 if a['language'] in ('ita', 'it') else 1
        return (lang_prio, a['index'])
    keep_audio.sort(key=sort_key)

    keep_subs = [s for s in all_subs if s['language'] in KEEP_LANGS]

    info = {
        'total_audio': len(all_audio),
        'total_subs': len(all_subs),
        'fallback_used': fallback_used,
    }
    return video, keep_audio, keep_subs, info


def describe_track(t):
    """Descrizione leggibile di una traccia audio."""
    ch = t['channels']
    suffix = f"{ch}.{max(0, ch-1)}" if ch > 0 else "?"
    codec = t['codec'].upper()
    lang = t['language'].upper()
    layout = t['channel_layout']
    return f"{lang} {suffix} {codec} ({layout})" if layout else f"{lang} {suffix} {codec}"


# ─────────────────────────────────────────────
# 2. SKIP INTELLIGENTE
# ─────────────────────────────────────────────

def needs_conversion(video, audio, subs, info):
    """
    Decide se il file ha bisogno di processing.
    Restituisce (bool, motivo).
    """
    # Tracce audio non ITA/ENG da scartare (ma esistono ITA/ENG)
    if not info['fallback_used'] and len(audio) < info['total_audio']:
        diff = info['total_audio'] - len(audio)
        return True, f"rimuove {diff} traccia/e audio non ITA/ENG"

    # Sottotitoli non ITA/ENG da scartare
    if len(subs) < info['total_subs']:
        diff = info['total_subs'] - len(subs)
        return True, f"rimuove {diff} sub non ITA/ENG"

    # Tracce audio non Z906-compatibili?
    for a in audio:
        codec = a['codec']
        ch = a['channels']
        # AC3 ≤ 6 canali → già OK per Z906
        if codec == 'ac3' and ch <= 6:
            continue
        # Stereo o mono → copiato così com'è (Z906 fa Pro Logic II)
        if 0 < ch <= 2:
            continue
        # Altrimenti serve conversione
        return True, f"converte {codec.upper()} {ch}ch → AC3 5.1"

    return False, "già Z906-compatibile"


# ─────────────────────────────────────────────
# 3. ESECUZIONE FFMPEG (progress bar live)
# ─────────────────────────────────────────────

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

        while b'\r' in stderr_buf:
            raw_line, _, stderr_buf = stderr_buf.partition(b'\r')
            line = raw_line.decode('utf-8', errors='replace').strip()
            if not line:
                continue
            stderr_chunks.append(line)

            if total_dur > 0 and 'time=' in line:
                try:
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
    print(file=sys.stderr)

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
# 4. COSTRUZIONE COMANDO FFMPEG
# ─────────────────────────────────────────────

def build_command(input_file, output_file, video, audio, subs, upmix):
    """Costruisce il comando ffmpeg con tutte le opzioni per-stream."""
    cmd = [
        'ffmpeg', '-i', str(input_file), '-y', '-stats',
        '-map_metadata', '0',
    ]

    if video:
        cmd += ['-map', f'0:{video[0]["index"]}', '-c:v', 'copy']
        print(f"    ✅ Video: {video[0]['codec']} copiato (nessuna modifica)")

    ao = 0
    for a in audio:
        cmd += ['-map', f'0:{a["index"]}']
        ch = a['channels']

        if ch >= 7:
            print(f"    🔄 [{ao}] {describe_track(a)} → AC3 5.1 640k (downmix 7.1→5.1)")
            cmd += [
                f'-c:a:{ao}', 'ac3',
                f'-b:a:{ao}', '640k',
                f'-ac:a:{ao}', '6',
            ]
        elif ch == 6:
            # Già 5.1 ma in formato non-AC3 (DTS, FLAC, ecc)
            if a['codec'] == 'ac3':
                print(f"    ✅ [{ao}] {describe_track(a)} copiato (già AC3 5.1)")
                cmd += [f'-c:a:{ao}', 'copy']
            else:
                print(f"    🔄 [{ao}] {describe_track(a)} → AC3 640k")
                cmd += [
                    f'-c:a:{ao}', 'ac3',
                    f'-b:a:{ao}', '640k',
                    f'-ac:a:{ao}', '6',
                ]
        elif 0 < ch <= 2:
            if upmix:
                print(f"    🔄 [{ao}] {describe_track(a)} → AC3 5.1 640k (upmix stereo→surround)")
                cmd += [
                    f'-c:a:{ao}', 'ac3',
                    f'-b:a:{ao}', '640k',
                    f'-ac:a:{ao}', '6',
                    f'-filter:a:{ao}', 'surround=chl_out=5.1',
                ]
            else:
                print(f"    ✅ [{ao}] {describe_track(a)} copiato (Z906 → Pro Logic II)")
                cmd += [f'-c:a:{ao}', 'copy']
        else:
            print(f"    ✅ [{ao}] {describe_track(a)} copiato")
            cmd += [f'-c:a:{ao}', 'copy']

        ao += 1

    for s in subs:
        lang_label = s['language'].upper()
        codec = s['codec']
        cmd += ['-map', f'0:{s["index"]}']
        print(f"    ✅ Sottotitoli {lang_label} ({codec}) mantenuti")

    if subs:
        cmd += ['-c:s', 'copy']

    cmd.append(str(output_file))
    return cmd


# ─────────────────────────────────────────────
# 5. VERIFICA OUTPUT
# ─────────────────────────────────────────────

def verify_output(output_file, expected_duration, expected_audio, expected_video):
    """Verifica integrità dell'output con ffprobe.
    Restituisce (ok, messaggio).
    """
    if not output_file.exists():
        return False, "file non esiste"
    if output_file.stat().st_size < 1024:  # < 1KB → sicuramente rotto
        return False, f"file troppo piccolo ({output_file.stat().st_size} byte)"

    try:
        data = probe(output_file)
    except subprocess.TimeoutExpired:
        return False, "ffprobe timeout"
    except (json.JSONDecodeError, OSError) as e:
        return False, f"ffprobe fallito: {e}"

    out_dur = float(data.get('format', {}).get('duration', 0))
    if expected_duration > 0 and out_dur < expected_duration * DURATION_TOLERANCE:
        return False, (
            f"durata troncata: {fmt_time(out_dur)} vs "
            f"{fmt_time(expected_duration)} attesi"
        )

    streams = data.get('streams', [])
    out_audio = sum(1 for s in streams if s['codec_type'] == 'audio')
    out_video = sum(1 for s in streams if s['codec_type'] == 'video')

    if out_audio < expected_audio:
        return False, f"audio mancante: {out_audio}/{expected_audio}"
    if out_video < expected_video:
        return False, f"video mancante: {out_video}/{expected_video}"

    return True, "OK"


# ─────────────────────────────────────────────
# 6. SPAZIO DISCO
# ─────────────────────────────────────────────

def check_disk_space(target_dir, source_size):
    """Verifica spazio libero sufficiente per la conversione.
    target_dir = directory dove andrà l'output.
    source_size = dimensione del file sorgente in byte.
    """
    try:
        free = shutil.disk_usage(target_dir).free
    except OSError as e:
        return True, f"impossibile verificare ({e})"  # non blocca, solo warning

    needed = int(source_size * DISK_SAFETY_FACTOR)
    if free < needed:
        return False, (
            f"servono ~{fmt_size(needed)}, disponibili {fmt_size(free)}"
        )
    return True, ""


# ─────────────────────────────────────────────
# 7. ROLLBACK
# ─────────────────────────────────────────────

def rollback_inplace(filepath, backup_path, output_file):
    """Rollback in modalità --inplace:
    1. Elimina output parziale (potenzialmente corrotto)
    2. Ripristina originale (Z906_BAK_<nome> → <nome>)
    """
    if output_file.exists():
        try:
            print(f"     🗑️  Elimino output parziale: {output_file.name}")
            output_file.unlink()
        except OSError as e:
            print(f"        ⚠️  Errore eliminazione: {e}")

    if backup_path.exists():
        try:
            print(f"     ↩️  Ripristino: {backup_path.name} → {filepath.name}")
            backup_path.rename(filepath)
        except OSError as e:
            print(f"        ⚠️  Errore ripristino: {e}")
            print(f"        ⚠️  Backup ancora in: {backup_path.name}")


# ─────────────────────────────────────────────
# 8. PRE-SCAN
# ─────────────────────────────────────────────

def pre_scan(files, force):
    """Probe veloce di tutti i file per classificarli SKIP/PROCESS.
    Restituisce: (to_process, to_skip, broken)
    Ognuno è una lista di dict: {file, size, duration, reason}.
    """
    to_process = []
    to_skip = []
    broken = []

    print(f"\n🔍 Pre-scan di {len(files)} file...")
    for i, f in enumerate(files, 1):
        print(f"\r   [{i}/{len(files)}] {f.name[:50]:50}", end='', flush=True)
        try:
            data = probe(f)
        except subprocess.TimeoutExpired:
            broken.append({'file': f, 'reason': 'ffprobe timeout'})
            continue
        except (json.JSONDecodeError, OSError, subprocess.CalledProcessError) as e:
            broken.append({'file': f, 'reason': f'probe fallito: {e}'})
            continue

        try:
            video, audio, subs, info = classify_streams(data)
        except (KeyError, TypeError) as e:
            broken.append({'file': f, 'reason': f'classify fallito: {e}'})
            continue

        size = f.stat().st_size
        dur = float(data.get('format', {}).get('duration', 0))

        if not audio:
            broken.append({'file': f, 'reason': 'nessuna traccia audio'})
            continue

        needs, reason = needs_conversion(video, audio, subs, info)

        entry = {
            'file': f,
            'size': size,
            'duration': dur,
            'reason': reason,
            'audio_count': len(audio),
            'video_count': len(video),
        }

        if needs or force:
            to_process.append(entry)
        else:
            to_skip.append(entry)

    print(f"\r   {' ' * 70}", end='\r')  # pulisce la riga di progresso
    return to_process, to_skip, broken


# ─────────────────────────────────────────────
# 9. PROCESSA UN SINGOLO FILE
# ─────────────────────────────────────────────

def process_file(entry, output_dir, upmix, dry_run, inplace):
    """Elabora un singolo file MKV/MP4 (già pre-scansionato)."""
    filepath = entry['file']
    total_dur = entry['duration']
    expected_audio = entry['audio_count']
    expected_video = entry['video_count']

    print(f"\n{'─'*60}")
    print(f"📦  {filepath.name}")
    print(f"{'─'*60}")
    print(f"   Info: {fmt_size(entry['size'])} | {fmt_time(total_dur)}")
    print(f"   Motivo: {entry['reason']}")

    log_event('START', filepath.name, f"{fmt_size(entry['size'])}, {fmt_time(total_dur)}")

    # Re-probe per avere stream aggiornati (in caso il file sia cambiato)
    try:
        data = probe(filepath)
    except subprocess.TimeoutExpired:
        print("  ❌ TIMEOUT: ffprobe non risponde")
        log_event('FAIL', filepath.name, 'probe timeout')
        return False
    except Exception as e:
        print(f"  ❌ ERRORE probe: {e}")
        log_event('FAIL', filepath.name, f'probe: {e}')
        return False

    video, audio, subs, info = classify_streams(data)

    if info['fallback_used']:
        print("  ⚠️  Nessuna traccia ITA/ENG — mantengo TUTTE le tracce audio")

    print(f"   Video:     {len(video)} traccia(e)")
    print(f"   Audio:     {info['total_audio']} trovate → {len(audio)} selezionate")
    print(f"   Sub:       {info['total_subs']} trovate → {len(subs)} selezionati")

    if not audio:
        print("  ⚠️  Nessuna traccia audio — SKIP")
        log_event('FAIL', filepath.name, 'nessun audio')
        return False

    # ── Prepara output ──
    backup_path = None
    if inplace:
        backup_path = filepath.with_name(f"{BACKUP_PREFIX}{filepath.name}")
        output_file = to_mkv(filepath)

        if backup_path.exists() and not dry_run:
            print(f"\n  ⚠️  Backup esistente: {backup_path.name} — SKIP")
            log_event('SKIP', filepath.name, 'backup esistente')
            return False

        target_dir = filepath.parent
    else:
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
        output_file = to_mkv(output_dir / filepath.name)
        target_dir = output_dir

        if output_file.exists() and not dry_run:
            print(f"\n  ⚠️  Output esistente: {output_file.name}")
            resp = input("     Sovrascrivere? [s/N]: ").strip().lower()
            if resp != 's':
                print("     SKIP")
                log_event('SKIP', filepath.name, 'output esistente, no overwrite')
                return False

    # ── Check spazio disco ──
    if not dry_run:
        ok, msg = check_disk_space(target_dir, entry['size'])
        if not ok:
            print(f"  ❌ SPAZIO INSUFFICIENTE: {msg}")
            log_event('FAIL', filepath.name, f'disco: {msg}')
            return False

    # ── Inplace: rinomina originale → backup ──
    if inplace:
        if not dry_run:
            print(f"\n   📦 Rinomino originale → {backup_path.name}")
            try:
                filepath.rename(backup_path)
            except OSError as e:
                print(f"  ❌ ERRORE rename: {e}")
                log_event('FAIL', filepath.name, f'rename: {e}')
                return False
            input_for_ffmpeg = backup_path
        else:
            print(f"\n   🏁 DRY RUN: rinomino {filepath.name} → {backup_path.name}")
            input_for_ffmpeg = filepath
    else:
        input_for_ffmpeg = filepath

    # ── Costruisci comando ──
    cmd = build_command(input_for_ffmpeg, output_file, video, audio, subs, upmix)

    if dry_run:
        print(f"\n   🏁 DRY RUN — comando:")
        cmd_str = ' \\\n      '.join(cmd)
        print(f"      {cmd_str}")
        log_event('DRY', filepath.name, 'comando generato')
        return True

    # ── Esegui ──
    print(f"\n   ⏳ Conversione in corso...")
    sys.stdout.flush()
    t_start = time.time()

    try:
        r = run_ffmpeg(cmd, total_dur)

        if r.returncode != 0:
            print(f"  ❌ ERRORE (exit code {r.returncode})")
            err_lines = [l for l in r.stderr.split('\n') if l.strip()]
            for line in err_lines[-10:]:
                print(f"     {line}")
            if inplace:
                rollback_inplace(filepath, backup_path, output_file)
            log_event('FAIL', filepath.name, f'ffmpeg exit {r.returncode}')
            return False

        # ── Verifica output ──
        ok, msg = verify_output(output_file, total_dur, expected_audio, expected_video)
        if not ok:
            print(f"  ❌ VERIFICA FALLITA: {msg}")
            if inplace:
                rollback_inplace(filepath, backup_path, output_file)
            log_event('FAIL', filepath.name, f'verify: {msg}')
            return False

        elapsed = time.time() - t_start
        in_size = backup_path.stat().st_size if inplace else filepath.stat().st_size
        out_size = output_file.stat().st_size
        ratio = (out_size / in_size * 100) if in_size > 0 else 0
        savings = in_size - out_size

        print(f"  ✅ COMPLETATO → {output_file.name}")
        print(f"     Durata: {fmt_time(elapsed)}")
        print(f"     Dimensione: {fmt_size(out_size)} ({ratio:.0f}% originale)")
        print(f"     Risparmio:  {fmt_size(savings) if savings > 0 else '0 MB'}")

        log_event(
            'OK', filepath.name,
            f'{fmt_size(out_size)} ({ratio:.0f}%) in {fmt_time(elapsed)}',
        )
        return True

    except KeyboardInterrupt:
        print(f"\n  ⛔ Interrotto dall'utente — rollback in corso...")
        if inplace:
            rollback_inplace(filepath, backup_path, output_file)
        else:
            # Non-inplace: elimina solo l'output parziale, originale intatto
            if output_file.exists():
                try:
                    print(f"     🗑️  Elimino output parziale: {output_file.name}")
                    output_file.unlink()
                except OSError as e:
                    print(f"        ⚠️  Errore: {e}")
        log_event('STOP', filepath.name, 'interrotto da utente (Ctrl+C)')
        sys.exit(130)
    except subprocess.TimeoutExpired:
        print(f"  ❌ TIMEOUT (> 2 ore)")
        if inplace:
            rollback_inplace(filepath, backup_path, output_file)
        log_event('FAIL', filepath.name, 'timeout ffmpeg')
        return False
    except Exception as e:
        print(f"  ❌ ERRORE: {e}")
        if inplace:
            rollback_inplace(filepath, backup_path, output_file)
        log_event('FAIL', filepath.name, f'eccezione: {e}')
        return False


# ─────────────────────────────────────────────
# 10. MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='mkv-downmix',
        description=textwrap.dedent("""\
            Converti tracce audio MKV/MP4 per Logitech Z906 (cavo ottico).
            Il video viene copiato SENZA ricodifica — qualità originale preservata."""
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(f"""\
            Esempi:
              %(prog)s ~/Downloads/TORRENT/
              %(prog)s film.mkv
              %(prog)s . --output ~/Movies/Z906/ --upmix-stereo
              %(prog)s . --inplace --yes      (batch silenzioso)
              %(prog)s . --dry-run

            Backup prefix: {BACKUP_PREFIX}<nome>
            Log file:      {LOG_PATH}

            Dopo la conversione:
              TV (HDMI) → [cavo ottico TOSLINK] → Logitech Z906
              Imposta TV su "Bitstream" o "Pass-through" per audio HD
              Lo Z906 mostrerà "3D Dolby Digital" ✓
        """),
    )
    parser.add_argument('input', help='File MKV/MP4 o directory')
    parser.add_argument('-o', '--output', default=None,
                        help='Directory output (default: ./Z906-ready/)')
    parser.add_argument('--upmix-stereo', action='store_true',
                        help='Upmix 2.0 → 5.1 (default: lascia stereo per Pro Logic II)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Mostra cosa farebbe senza eseguire')
    parser.add_argument('--no-verify', action='store_true',
                        help='Salta verifica prerequisiti ffmpeg')
    parser.add_argument('--inplace', action='store_true',
                        help=f'Rinomina originale in {BACKUP_PREFIX}<nome> e sostituisce')
    parser.add_argument('--force', action='store_true',
                        help='Converti anche file già Z906-compatibili')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Salta conferma globale (utile in batch)')

    args = parser.parse_args()

    # ── Verifica prerequisiti ──
    if not args.dry_run and not args.no_verify:
        if not shutil.which('ffmpeg'):
            print("❌ ffmpeg non trovato. Installa con:  brew install ffmpeg")
            sys.exit(1)
        r = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True)
        if 'ac3' not in r.stdout:
            print("❌ Encoder AC3 non disponibile in ffmpeg.")
            print("   Reinstalla con: brew reinstall ffmpeg")
            sys.exit(1)
        print("✅ ffmpeg + encoder AC3 disponibili")

    # ── Input ──
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"❌ Input non trovato: {input_path}")
        sys.exit(1)

    if input_path.is_file():
        if is_backup(input_path.name):
            print(f"❌ {input_path.name} è un backup — niente da fare")
            sys.exit(1)
        files = [input_path]
    else:
        # Globbing escludendo i backup
        candidates = []
        for ext in ('*.mkv', '*.mka', '*.mp4'):
            candidates.extend(input_path.glob(ext))
        files = sorted(f for f in candidates if not is_backup(f.name))
        # Dedup mantenendo l'ordine
        seen = set()
        files = [f for f in files if not (f in seen or seen.add(f))]

    if not files:
        print(f"❌ Nessun file MKV/MKA/MP4 trovato in: {input_path}")
        print(f"   (i file con prefisso {BACKUP_PREFIX} sono ignorati)")
        sys.exit(1)

    # ── Header config ──
    print(f"\n{'═'*60}")
    print("CONFIGURAZIONE:")
    print(f"  Input:        {input_path}")
    print(f"  File trovati: {len(files)} (backup esclusi)")
    print(f"  Upmix stereo: {'SÌ' if args.upmix_stereo else 'NO (Pro Logic II)'}")
    print(f"  Modalità:     {'in-place' if args.inplace else 'output separato'}")
    print(f"  Force:        {'SÌ (no skip)' if args.force else 'NO (skip già OK)'}")
    print(f"  Dry run:      {'SÌ' if args.dry_run else 'NO'}")
    print(f"  Log:          {LOG_PATH}")
    print(f"{'═'*60}")

    # ── Pre-scan ──
    to_process, to_skip, broken = pre_scan(files, args.force)

    # ── Riepilogo ──
    total_size = sum(e['size'] for e in to_process)
    print(f"\n📊 Riepilogo pre-scan:")
    print(f"   ⚙️  Da processare: {len(to_process)} file ({fmt_size(total_size)})")
    print(f"   ⏭️  Da skippare:   {len(to_skip)} file (già Z906-compatibili)")
    if broken:
        print(f"   ⚠️  Problematici:  {len(broken)} file")
        for b in broken:
            print(f"      - {b['file'].name}: {b['reason']}")

    if to_skip and len(to_skip) <= 20:
        print(f"\n   File skippati:")
        for s in to_skip:
            print(f"      ✓ {s['file'].name}  ({s['reason']})")
    elif to_skip:
        print(f"   (lista skip troppo lunga, vedere log)")

    for s in to_skip:
        log_event('SKIP', s['file'].name, s['reason'])

    if not to_process:
        print(f"\n✅ Niente da fare — tutti i file sono già Z906-compatibili.")
        sys.exit(0)

    if args.dry_run:
        print(f"\n🏁 DRY RUN — mostro i comandi per i {len(to_process)} file da processare:")
    else:
        # ── Conferma globale ──
        size_gb = total_size / (1024**3)
        need_confirm = (
            len(to_process) >= CONFIRM_FILE_THRESHOLD or size_gb >= CONFIRM_SIZE_GB
        )
        if need_confirm and not args.yes:
            print(f"\n⏱️  Stima durata: ~{size_gb*0.4:.0f}–{size_gb*1.5:.0f} minuti")
            print(f"    (dipende da CPU, codec sorgente, e velocità storage)")
            try:
                resp = input(f"\nProcedere con {len(to_process)} file ({fmt_size(total_size)})? [s/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAnnullato.")
                sys.exit(0)
            if resp != 's':
                print("Annullato.")
                sys.exit(0)

    # ── Output dir ──
    output_dir = None
    if not args.inplace:
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
    elif not args.dry_run:
        print(f"\n📂 Output: in-place (originali → {BACKUP_PREFIX}<nome>)")

    # ── Processa ──
    log_event('BATCH', f'{len(to_process)} file', f'totale {fmt_size(total_size)}')
    ok = fail = 0
    for entry in to_process:
        if process_file(entry, output_dir, args.upmix_stereo, args.dry_run, args.inplace):
            ok += 1
        else:
            fail += 1

    # ── Riepilogo finale ──
    print(f"\n{'═'*60}")
    print(f"RIEPILOGO FINALE:")
    print(f"  ✅ Completati: {ok}")
    print(f"  ⏭️  Skippati:   {len(to_skip)}")
    if fail > 0:
        print(f"  ❌ Falliti:    {fail}")
    if broken:
        print(f"  ⚠️  Problematici: {len(broken)}")

    log_event('END', f'{ok} OK, {fail} FAIL, {len(to_skip)} SKIP', '')

    if ok > 0 and not args.dry_run:
        if args.inplace:
            cleanup_dir = input_path if input_path.is_dir() else input_path.parent
            print(f"\n📂 File in-place — originali in {BACKUP_PREFIX}<nome>")
            print(f"   Per liberare spazio quando hai verificato:")
            print(f"     rm \"{cleanup_dir}\"/{BACKUP_PREFIX}*")
        else:
            print(f"\n📂 Output: {output_dir}")
        print(f"\n💡 Setup hardware:")
        print(f"   1. TV → Z906 via cavo ottico (TOSLINK)")
        print(f"   2. Audio TV: \"Bitstream\" o \"Pass-through\"")
        print(f"   3. Lo Z906 mostrerà \"3D Dolby Digital\" ✓")
    print(f"{'═'*60}")


if __name__ == '__main__':
    main()
