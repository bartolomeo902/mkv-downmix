# Project Context

## Environment
- Language: Python 3
- Runtime: python3
- Build: N/A (script-based)
- Test: N/A (script-based, manual verification via ffprobe)
- Package Manager: N/A (no dependencies beyond FFmpeg)

## Project Type
- [x] Application (CLI)
- [ ] Library/Package
- [ ] Microservice
- [ ] Monorepo
- [ ] Other: [describe]

## Infrastructure
- Container: None
- Orchestration: None
- CI/CD: None
- Cloud: None

## Structure
- Source: `/Users/bartolomeo/repos/mkv-downmix/mkv-downmix.py`
- Tests: None
- Docs: `README.md`
- Entry: `mkv-downmix.py`

## Conventions
- Naming: snake_case (Python)
- Imports: standard library only (subprocess, json, os, sys, argparse, shutil, textwrap, pathlib)
- Error handling: exceptions, return codes
- Testing: manual (dry-run mode, ffprobe verification)

## External Dependencies
- FFmpeg 8.1.2 (via Homebrew)
- Encoder AC3 (ac3, eac3, ac3_fixed)

## Prerequisites Verified
- [x] FFmpeg installed: version 8.1.2
- [x] AC3 encoder available
- [x] GitHub remote: github.com/bartolomeo902/mkv-downmix.git
- [x] Script syntax OK (401 lines)

## Notes
- Script converts MKV audio tracks for Logitech Z906 (TOSLINK optical)
- Video is stream-copied (no re-encode, zero risk)
- Output goes to `Z906-ready/` subdirectory by default
- User must provide source directory with real MKV files
