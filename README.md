# Husk

A local, standard-library-only Python GUI tool for safely stripping the
bloat off a Windows PC — no third-party dependencies, no telemetry,
nothing sent anywhere.

![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

## Features

| Tab | What it does |
|---|---|
| **Quick Cleanup** | Scans and clears TEMP folders, empties the Recycle Bin, clears browser caches (Chrome/Edge/Firefox) |
| **Startup Manager** | Lists Run-key startup entries; disable/re-enable with a local JSON backup so nothing is ever lost |
| **Visual Effects** | Toggles animations, transparency, window shadows, menu delay — the same registry keys Windows' own performance settings expose |
| **Services** | Start/stop/set-startup-type for a *curated* list of optional services only (Superfetch, telemetry, Windows Search, Fax, etc.) — never the full service list |
| **System Info** | RAM, disk, and CPU snapshot |

## Requirements

- Windows 10 or 11
- Python 3.9+
- No `pip install` needed — uses only the standard library (`tkinter`,
  `winreg`, `ctypes`, `subprocess`, `shutil`)

## Usage

```bash
python husk.py
```

For **Startup Manager** and **Services**, run as Administrator — either
right-click the script → *Run as administrator*, or use the in-app
"Restart as Administrator" button that appears when not elevated.

## Safety

- Every registry write targets a known, documented, reversible key —
  the same ones exposed by Windows' own Settings app / System Restore.
- Disabling a startup item backs it up to `startup_backup.json` next to
  the script, so it can always be restored from within the app.
- The Services tab exposes only a small, curated list of non-critical
  services — never anything related to Windows Update, security, or
  drivers.

## Project structure

```
.
├── husk.py                # the app
├── README.md
├── LICENSE
└── .gitignore
```

`startup_backup.json` is created automatically the first time you
disable a startup item; it's machine-specific and git-ignored.

## Contributing

Issues and PRs welcome — in particular, additions to the curated
`SAFE_SERVICES` list should include a short risk note, same as the
existing entries.

## Author

**Devdutt Parab**
Email: [devduttparab@gmail.com](mailto:devduttparab@gmail.com)
LinkedIn: [linkedin.com/in/devdutt-parab](https://www.linkedin.com/in/devdutt-parab/)

## License

MIT — see [LICENSE](LICENSE).
