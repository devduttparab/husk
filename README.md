# Husk

A lightweight, zero-dependency Python GUI tool to clean, optimize, and manage Windows systems safely.

Built using only Python standard library (Tkinter, ctypes, winreg, subprocess).

---

## 🚀 Why Husk?

Most PC optimization tools:
- Install unnecessary software
- Track user data
- Modify system settings blindly

**Husk is different:**
- ❌ No telemetry
- ❌ No external dependencies
- ✅ Fully transparent operations
- ✅ Safe & reversible changes only

---

## 🧩 Features

### 🧹 Quick Cleanup
- Clears TEMP folders
- Empties Recycle Bin
- Removes browser cache (Chrome, Edge, Firefox)

### ⚙️ Startup Manager
- View startup programs
- Disable safely (with backup)
- Restore anytime

### 🎨 Visual Effects
- Toggle animations, shadows, transparency
- Improve performance on low-end machines

### 🔧 Services Manager
- Control only *safe, non-critical* services
- No risk to system stability

### 📊 System Info
- RAM usage
- Disk usage
- CPU snapshot

---

## 🛡️ Safety First

- Registry changes are **limited + reversible**
- Startup items backed up in `startup_backup.json`
- Only curated services are exposed
- No system-critical services touched

---

## 🖥️ Requirements

- Windows 10 / 11
- Python 3.9+
- No external libraries required

---

## ▶️ Run

```bash
python husk.py
