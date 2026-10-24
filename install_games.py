#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_games.py — Instalador de juegos para Fedora (KDE/Discover).

Reglas:
  * Prioridad de formato: Flatpak > DNF > Snap.
  * Un juego se instala UNA sola vez: si existe en Flatpak no se instala por
    DNF ni Snap; si existe en DNF no se instala por Snap.
  * Los duplicados ya instalados se eliminan (se conserva la versión Flatpak;
    si no hay Flatpak, se conserva la de DNF y se quita la de Snap).
  * Nunca instala Steam ni plataformas para juegos de Windows
    (Wine, Bottles, Lutris, PlayOnLinux, Q4Wine, Faugus, Heroic, Proton*, etc.).
  * Concede permisos: interfaces Snap conectadas y acceso a mandos/dispositivos
    (--device=all) para los juegos Flatpak.

Uso:
  python3 install_games.py              # interactivo (pide sudo si hace falta)
  python3 install_games.py --dry-run    # simulación, no cambia nada
  python3 install_games.py --yes        # sin preguntas
  python3 install_games.py --no-snap    # no usar Snap
  python3 install_games.py --no-dnf     # no usar DNF
"""

import argparse
import glob
import gzip
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

# --------------------------------------------------------------------------- #
#  Colores y registro
# --------------------------------------------------------------------------- #
C = {"b": "\033[1m", "r": "\033[91m", "g": "\033[92m", "y": "\033[93m",
     "c": "\033[96m", "d": "\033[2m", "x": "\033[0m"}
if not sys.stdout.isatty():
    C = {k: "" for k in C}

LOG_PATH = None


def log(msg="", color=None, end="\n"):
    text = f"{C[color]}{msg}{C['x']}" if color else msg
    print(text, end=end, flush=True)
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(re.sub(r"\033\[[0-9;]*m", "", msg) + ("\n" if end == "\n" else ""))
        except OSError:
            pass


def run_cmd(args, env=None, timeout=None, as_user=None):
    """Ejecuta un comando y devuelve (código, stdout, stderr)."""
    cmd_env = os.environ.copy()
    if env:
        cmd_env.update(env)
    if as_user and os.geteuid() == 0:
        args = ["sudo", "-u", as_user, "-H"] + list(args)
    try:
        r = subprocess.run(args, capture_output=True, text=True, errors="replace",
                           check=False, env=cmd_env, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"tiempo agotado ({timeout}s)"
    except FileNotFoundError:
        return -2, "", f"comando '{args[0]}' no encontrado"


def run_live(args, timeout=None):
    """Ejecuta mostrando la salida en pantalla; devuelve el código."""
    try:
        return subprocess.run(args, check=False, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return -1
    except FileNotFoundError:
        return -2


# --------------------------------------------------------------------------- #
#  Lista negra: Steam y plataformas para juegos de Windows
# --------------------------------------------------------------------------- #
BLOCKED_ID_PREFIXES = (
    "com.valvesoftware.",            # Steam, Steam Link, compat tools
    "org.winehq.",                   # Wine
    "com.usebottles.",               # Bottles
    "net.lutris.",                   # Lutris
    "com.heroicgameslauncher.",      # Heroic
    "com.playonlinux.",              # PlayOnLinux
    "org.phoenicis.",                # PlayOnLinux 5 / Phoenicis
    "io.github.faugus.",             # Faugus Launcher
    "io.github.fastrizwaan.",        # WineZGUI / WineCharm
    "net.davidotek.pupgui2",         # ProtonUp-Qt
    "com.vysp3r.protonplus",         # ProtonPlus
    "com.github.matoking.protontricks",
    "io.github.sharkwouter.minigalaxy",
    "com.github.tkashkin.gamehub",
    "io.github.dummerle.rare",       # Rare (Epic)
    "io.github.derrod.legendary",    # Legendary (Epic)
    "com.steamgriddb.",              # Steam ROM Manager
    "io.github.philipk.boilr",       # BoilR (Steam)
    "org.vinegarhq.vinegar",         # Vinegar (Roblox Studio con Wine)
    "ru.linux_gaming.portproton",    # PortProton (Wine/Proton)
    "dev.goats.xivlauncher",         # XIVLauncher (FFXIV con Wine)
    "cn.ottercorp.xivlaunchercn",    # XIVLauncher CN
    "moe.launcher.",                 # Anime Game / Honkers / Sleepy Launcher (Wine)
    "app.twintaillauncher.",         # Twintail Launcher (Wine/Proton)
    "io.thenexusavenger.nexus-lu-launcher",  # LEGO Universe con Wine
    "io.github.foldex.adwsteamgtk",  # Tema para Steam
)
# Segmentos exactos de un ID / nombre de paquete
BLOCKED_TOKENS = {
    "steam", "steamcmd", "steamlink", "steamos", "steamtinkerlaunch", "steamdeck",
    "valve", "valvesoftware",
    "wine", "winehq", "winetricks", "wineasio", "winezgui", "winecharm", "winegui",
    "q4wine", "lutris", "bottles", "usebottles", "playonlinux", "playonlinux4",
    "phoenicis", "faugus", "fangus", "heroic", "heroicgameslauncher",
    "proton", "protonup", "protonupqt", "pupgui2", "protontricks", "protonplus",
    "minigalaxy", "gamehub", "crossover", "cxoffice", "boxtron", "luxtorpeda",
    "dxvk", "vkd3d", "umu", "umulauncher", "boilr",
    "portproton", "xivlauncher", "xivlaunchercn", "adwsteamgtk",
}
# Expresiones sobre el nombre visible
BLOCKED_NAME_RE = re.compile(
    r"\bsteam\b|\bwine(hq|tricks|zgui|charm)?\b|\bq4wine\b|\blutris\b|\bbottles\b|"
    r"\bplay ?on ?linux\b|\bfaugus\b|\bheroic games\b|\bproton ?(up|plus|tricks|ge)?\b|"
    r"\bminigalaxy\b|\bgamehub\b|\bcrossover\b|\bportproton\b|\bxivlauncher\b",
    re.IGNORECASE,
)


def is_blocked(ident="", name=""):
    low = (ident or "").lower()
    if low.startswith(BLOCKED_ID_PREFIXES):
        return True
    tokens = {t for t in re.split(r"[^a-z0-9]+", low) if t}
    if tokens & BLOCKED_TOKENS:
        return True
    if name and BLOCKED_NAME_RE.search(name):
        return True
    return False


# --------------------------------------------------------------------------- #
#  Claves de comparación (para detectar el mismo juego en distintos formatos)
# --------------------------------------------------------------------------- #
PKG_PREFIXES = ("gnome-", "kde-", "xfce4-", "mate-", "gtk-", "qt-", "sdl-", "python3-")
PKG_SUFFIXES = ("-game", "-games", "-gtk", "-qt", "-sdl", "-sdl2", "-bin", "-git")


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def keys_for(name=None, ident=None, kind=None):
    """Conjunto de claves normalizadas que identifican un juego."""
    keys = set()
    if name:
        keys.add(norm(name))
    if ident:
        if kind == "flatpak" or kind == "desktop":
            ident = re.sub(r"\.desktop$", "", ident)
            keys.add(norm(ident.split(".")[-1]))
        else:
            keys.add(norm(ident))
            stripped = ident.lower()
            for p in PKG_PREFIXES:
                if stripped.startswith(p):
                    stripped = stripped[len(p):]
            for s in PKG_SUFFIXES:
                if stripped.endswith(s):
                    stripped = stripped[: -len(s)]
            keys.add(norm(stripped))
    # Claves demasiado cortas generan falsos positivos
    return {k for k in keys if len(k) >= 3}


def read_desktop(path):
    """Devuelve (Name, Categories, NoDisplay) de un .desktop."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return None, "", False
    entry = content.split("[Desktop Entry]", 1)[-1].split("\n[", 1)[0]
    name = re.search(r"^Name=(.*)$", entry, re.MULTILINE)
    cats = re.search(r"^Categories=(.*)$", entry, re.MULTILINE)
    nod = re.search(r"^NoDisplay=true", entry, re.MULTILINE)
    return (name.group(1).strip() if name else None,
            cats.group(1) if cats else "", bool(nod))


def is_game_desktop(categories):
    return "Game" in [c.strip() for c in categories.split(";")]


# --------------------------------------------------------------------------- #
#  Entorno
# --------------------------------------------------------------------------- #
def real_user_info():
    user = os.environ.get("SUDO_USER") or os.environ.get("PKEXEC_UID")
    if user and user.isdigit():
        try:
            user = pwd.getpwuid(int(user)).pw_name
        except KeyError:
            user = None
    if not user or user == "root":
        try:
            user = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            user = None
    home = None
    if user:
        try:
            home = pwd.getpwnam(user).pw_dir
        except KeyError:
            pass
    return user, home


def ensure_root(argv):
    """Se relanza con sudo si hace falta (excepto en simulación)."""
    if os.geteuid() == 0 or "--dry-run" in argv:
        return
    script = os.path.abspath(__file__)
    for tool in ("sudo", "pkexec"):
        if shutil.which(tool):
            print(f"[*] Se requieren privilegios de administrador; relanzando con {tool}...")
            os.execvp(tool, [tool, sys.executable, script] + argv)
    print("[-] Ejecuta este script como administrador (sudo).")
    sys.exit(1)


# --------------------------------------------------------------------------- #
#  Flatpak
# --------------------------------------------------------------------------- #
def flatpak_prepare(dry_run):
    if not shutil.which("flatpak"):
        if dry_run:
            log("[Simulación] Se instalaría flatpak con DNF.", "y")
            return True
        log("[*] Flatpak no está instalado. Instalando...")
        if run_cmd(["dnf", "install", "-y", "flatpak"], timeout=600)[0] != 0:
            log("[-] No se pudo instalar Flatpak.", "r")
            return False
    if dry_run:
        return True
    code, _, err = run_cmd(["flatpak", "remote-add", "--system", "--if-not-exists", "flathub",
                            "https://dl.flathub.org/repo/flathub.flatpakrepo"], timeout=120)
    if code != 0:
        log(f"[!] No se pudo añadir Flathub: {err.strip()}", "y")
    # Por si estaba deshabilitado (Fedora lo trae filtrado/deshabilitado a veces)
    run_cmd(["flatpak", "remote-modify", "--system", "--enable", "--no-filter", "flathub"], timeout=60)
    log("[*] Actualizando catálogo AppStream de Flatpak...")
    run_cmd(["flatpak", "update", "--system", "--appstream", "-y"], timeout=600)
    return True


def get_installed_flatpaks(user):
    """{app_id: name} de todas las apps Flatpak (sistema + usuario)."""
    apps = {}
    for as_user in ([user] if user else []) + [None]:
        code, out, _ = run_cmd(["flatpak", "list", "--app", "--columns=application,name"],
                               timeout=60, as_user=as_user)
        if code == 0:
            for line in out.splitlines():
                parts = line.split("\t")
                if parts and parts[0].strip():
                    apps[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else parts[0].strip()
            if apps:
                break
    return apps


def get_flatpak_catalog():
    """{app_id: (name, remote)} de los juegos del catálogo (AppStream local / API Flathub)."""
    games = {}
    arch = os.uname().machine
    files = glob.glob(f"/var/lib/flatpak/appstream/*/{arch}/active/appstream.xml.gz") + \
        glob.glob(f"/var/lib/flatpak/appstream/*/{arch}/active/appstream.xml")
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
    for path in files:
        remote = path.split("/")[5]
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rb") as fh:
                for _, elem in ET.iterparse(fh, events=("end",)):
                    if elem.tag != "component":
                        continue
                    cats = [c.text for c in elem.findall("categories/category") if c.text]
                    bundle = elem.find("bundle")
                    if "Game" in cats and bundle is not None and (bundle.text or "").startswith("app/"):
                        app_id = bundle.text.split("/")[1]
                        name = app_id
                        for n in elem.findall("name"):
                            if not n.attrib.get(xml_lang) and n.text:
                                name = n.text.strip()
                                break
                        if app_id not in games or remote == "flathub":
                            games[app_id] = (name, remote)
                    elem.clear()
        except (OSError, ET.ParseError, EOFError):
            continue

    if len(games) < 50:  # Respaldo: API pública de Flathub
        try:
            page = 1
            while True:
                url = f"https://flathub.org/api/v2/collection/category/Game?per_page=250&page={page}"
                req = urllib.request.Request(url, headers={"User-Agent": "install-games-script/2.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                for h in data.get("hits", []):
                    if h.get("app_id"):
                        games.setdefault(h["app_id"], (h.get("name") or h["app_id"], "flathub"))
                if page >= int(data.get("totalPages") or 1) or not data.get("hits"):
                    break
                page += 1
        except Exception as e:  # noqa: BLE001
            log(f"[!] No se pudo consultar la API de Flathub: {e}", "y")
    return games


def flatpak_install(app_id, remote, verbose):
    base = ["flatpak", "install", "--system", "-y", "--noninteractive"]
    for cmd in (base + [remote, app_id], base + ["flathub", app_id], base + [app_id]):
        code = run_live(cmd, timeout=3600) if verbose else run_cmd(cmd, timeout=3600)[0]
        if code == 0:
            return True
    return False


def flatpak_grant_permissions(app_id):
    """Acceso a mandos/joysticks y dispositivos de entrada."""
    run_cmd(["flatpak", "override", "--system", "--device=all", app_id], timeout=30)


# --------------------------------------------------------------------------- #
#  DNF / RPM
# --------------------------------------------------------------------------- #
def get_installed_rpms():
    code, out, _ = run_cmd(["rpm", "-qa", "--qf", "%{NAME}\n"], timeout=60)
    return {l.strip() for l in out.splitlines() if l.strip()} if code == 0 else set()


def get_installed_rpm_games(dnf_group_pkgs, installed_rpms):
    """{paquete: claves} de juegos instalados como RPM."""
    games = {}
    for path in glob.glob("/usr/share/applications/*.desktop"):
        name, cats, _ = read_desktop(path)
        if not is_game_desktop(cats):
            continue
        code, out, _ = run_cmd(["rpm", "-qf", "--qf", "%{NAME}\n", path], timeout=15)
        pkg = out.strip().splitlines()[0] if code == 0 and out.strip() else None
        if not pkg:
            continue
        k = games.setdefault(pkg, set())
        k |= keys_for(name=name) | keys_for(ident=os.path.basename(path), kind="desktop") \
            | keys_for(ident=pkg, kind="rpm")
    for pkg in dnf_group_pkgs & installed_rpms:
        games.setdefault(pkg, set()).update(keys_for(ident=pkg, kind="rpm"))
    return games


def get_dnf_games_group():
    """Paquetes del grupo 'games' de DNF (compatible dnf4 y dnf5)."""
    code, out, _ = run_cmd(["dnf", "-q", "group", "info", "games"],
                           env={"LC_ALL": "C", "LANG": "C"}, timeout=600)
    pkgs, in_list = set(), False
    if code != 0:
        return pkgs
    valid = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_.+]*$")
    for line in out.splitlines():
        if not line.strip():
            in_list = False
            continue
        if ":" in line:
            label, _, value = line.partition(":")
            label, value = label.strip().lower(), value.strip()
            if label.endswith("packages"):
                in_list = True
            elif label:
                in_list = False
                continue
            if in_list and value and valid.match(value):
                pkgs.add(value)
        elif in_list:
            value = line.strip().lstrip("=+-")
            if valid.match(value):
                pkgs.add(value)
    return pkgs


def rpm_removable(pkg):
    """True si ningún otro paquete depende de él."""
    return run_cmd(["rpm", "-e", "--test", pkg], timeout=60)[0] == 0


# --------------------------------------------------------------------------- #
#  Snap
# --------------------------------------------------------------------------- #
def snap_bin():
    return shutil.which("snap") or ("/usr/bin/snap" if os.path.exists("/usr/bin/snap") else None)


def ensure_snapd(dry_run, allow_install):
    if snap_bin():
        if not dry_run:
            run_cmd(["systemctl", "enable", "--now", "snapd.socket"], timeout=30)
            run_cmd([snap_bin(), "wait", "system", "seed.loaded"], timeout=180)
        return snap_bin()
    if not allow_install:
        log("[!] snapd no está instalado; se omiten los juegos Snap.", "y")
        return None
    if dry_run:
        log("[Simulación] Se instalaría snapd (solo se usará para juegos que no existan en Flatpak ni DNF).", "y")
        return None
    log("[*] Instalando snapd...")
    if run_cmd(["dnf", "install", "-y", "snapd"], timeout=600)[0] != 0:
        log("[-] No se pudo instalar snapd; se omiten los juegos Snap.", "r")
        return None
    run_cmd(["systemctl", "enable", "--now", "snapd.socket"], timeout=30)
    if not os.path.exists("/snap"):
        run_cmd(["ln", "-s", "/var/lib/snapd/snap", "/snap"], timeout=10)
    run_cmd([snap_bin() or "snap", "wait", "system", "seed.loaded"], timeout=300)
    return snap_bin()


def get_installed_snaps(sb):
    if not sb:
        return set()
    code, out, _ = run_cmd([sb, "list"], timeout=60)
    if code != 0:
        return set()
    return {l.split()[0] for l in out.splitlines()[1:] if l.split()}


def get_installed_snap_games(sb, installed_snaps, snap_catalog):
    games = {}
    for path in glob.glob("/var/lib/snapd/desktop/applications/*.desktop"):
        name, cats, _ = read_desktop(path)
        if not is_game_desktop(cats):
            continue
        snap = os.path.basename(path).split("_")[0]
        if snap in installed_snaps:
            games.setdefault(snap, set()).update(keys_for(name=name) | keys_for(ident=snap, kind="snap"))
    for snap in installed_snaps & set(snap_catalog):
        games.setdefault(snap, set()).update(keys_for(ident=snap, kind="snap"))
    return games


def get_snap_catalog(sb):
    if not sb:
        return []
    code, out, err = run_cmd([sb, "find", "--section=games"], timeout=120)
    if code != 0:
        log(f"[!] No se pudo listar la sección de juegos de Snap: {err.strip()}", "y")
        return []
    return [l.split()[0] for l in out.splitlines()[1:] if l.split()]


def snap_install(sb, name, verbose):
    code, out, _ = run_cmd([sb, "info", name], timeout=60)
    cmd = [sb, "install", name]
    if code == 0 and re.search(r"^\s*confinement:\s*classic", out, re.MULTILINE):
        cmd.append("--classic")
    rc = run_live(cmd, timeout=3600) if verbose else run_cmd(cmd, timeout=3600)[0]
    return rc == 0


def snap_grant_permissions(sb, name):
    code, out, _ = run_cmd([sb, "connections", name], timeout=30)
    if code != 0:
        return
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "-":
            run_cmd([sb, "connect", parts[1]], timeout=30)


# --------------------------------------------------------------------------- #
#  Steam (solo para NO duplicar juegos que ya tengas ahí; nunca se instala)
# --------------------------------------------------------------------------- #
def get_steam_game_keys(home):
    keys = set()
    if not home:
        return keys
    for d in (f"{home}/.local/share/Steam/steamapps",
              f"{home}/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps"):
        for acf in glob.glob(os.path.join(d, "appmanifest_*.acf")):
            try:
                with open(acf, encoding="utf-8", errors="ignore") as f:
                    m = re.search(r'"name"\s+"([^"]+)"', f.read())
                if m:
                    keys |= keys_for(name=m.group(1))
            except OSError:
                pass
    return keys


# --------------------------------------------------------------------------- #
#  Utilidades
# --------------------------------------------------------------------------- #
def confirm(question, assume_yes):
    if assume_yes:
        return True
    try:
        return input(f"{question} [S/n]: ").strip().lower() not in ("n", "no")
    except (KeyboardInterrupt, EOFError):
        print()
        return False


def header():
    log("=" * 64, "c")
    log("   INSTALADOR DE JUEGOS  ·  Flatpak > DNF > Snap  ·  sin duplicados", "b")
    log("   (sin Steam ni plataformas para juegos de Windows)", "d")
    log("=" * 64, "c")


# --------------------------------------------------------------------------- #
#  Programa principal
# --------------------------------------------------------------------------- #
def main():
    global LOG_PATH
    argv = sys.argv[1:]
    p = argparse.ArgumentParser(description="Instala juegos sin duplicados (prioridad Flatpak > DNF > Snap).")
    p.add_argument("--dry-run", action="store_true", help="Simular sin hacer cambios.")
    p.add_argument("-y", "--yes", action="store_true", help="No pedir confirmaciones.")
    p.add_argument("--no-dnf", action="store_true", help="No instalar juegos con DNF.")
    p.add_argument("--no-snap", action="store_true", help="No instalar juegos con Snap.")
    p.add_argument("--no-snapd-install", action="store_true", help="No instalar snapd si falta.")
    p.add_argument("--solo-limpiar", action="store_true", help="Solo eliminar duplicados, sin instalar.")
    p.add_argument("--verbose", action="store_true", help="Mostrar la salida de los instaladores.")
    args = p.parse_args(argv)

    ensure_root(argv)
    user, home = real_user_info()
    immutable = os.path.exists("/run/ostree-booted")
    if home and not args.dry_run:
        LOG_PATH = os.path.join(home, "install_games.log")
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            if user and os.geteuid() == 0:
                pw = pwd.getpwnam(user)
                os.chown(LOG_PATH, pw.pw_uid, pw.pw_gid)
        except OSError:
            LOG_PATH = None

    header()
    if args.dry_run:
        log("[MODO SIMULACIÓN] No se realizarán cambios.\n", "y")

    if immutable and not (args.no_dnf and args.no_snap):
        log("[i] Sistema inmutable (rpm-ostree: Silverblue, Kinoite, Bazzite...): "
            "solo se usará Flatpak; DNF y Snap no están disponibles.", "y")
        args.no_dnf = args.no_snap = True

    # ---------- 1. Preparación ----------
    if not flatpak_prepare(args.dry_run):
        sys.exit(1)
    use_snap = not args.no_snap
    sb = ensure_snapd(args.dry_run, not args.no_snapd_install) if use_snap else None

    # ---------- 2. Inventario ----------
    log("\n[*] Leyendo catálogos y juegos instalados...")
    fp_catalog = {a: v for a, v in get_flatpak_catalog().items()}
    blocked_fp = sorted(v[0] for a, v in fp_catalog.items() if is_blocked(a, v[0]))
    fp_catalog = {a: v for a, v in fp_catalog.items() if not is_blocked(a, v[0])}

    dnf_group = set() if args.no_dnf else get_dnf_games_group()
    dnf_group = {pkg for pkg in dnf_group if not is_blocked(pkg)}
    snap_catalog = [s for s in get_snap_catalog(sb) if not is_blocked(s)] if use_snap else []

    installed_fp = get_installed_flatpaks(user)
    installed_rpms = get_installed_rpms()
    installed_snaps = get_installed_snaps(sb)
    steam_keys = get_steam_game_keys(home)

    log(f"    Catálogo Flatpak (juegos)  : {len(fp_catalog)}  "
        f"{C['d']}(excluidos Steam/Windows: {len(blocked_fp)}){C['x']}")
    log(f"    Grupo de juegos DNF        : {len(dnf_group)}")
    log(f"    Sección de juegos Snap     : {len(snap_catalog)}")
    log(f"    Flatpak instalados         : {len(installed_fp)}")

    # ---------- 3. Cola Flatpak ----------
    fp_queue = []
    if not args.solo_limpiar:
        for app_id, (name, remote) in sorted(fp_catalog.items(), key=lambda x: x[1][0].lower()):
            if app_id in installed_fp:
                continue
            if keys_for(name=name, ident=app_id, kind="flatpak") & steam_keys:
                continue  # ya lo tienes en tu biblioteca de Steam
            fp_queue.append((app_id, name, remote))

    log(f"\n[*] Juegos Flatpak por instalar: {C['b']}{len(fp_queue)}{C['x']}")
    if fp_queue and not args.dry_run:
        log("    Aviso: instalar todo el catálogo puede ocupar cientos de GB.", "y")
        if not confirm("¿Instalar los juegos Flatpak pendientes?", args.yes):
            fp_queue = []

    fp_ok, fp_fail = [], []
    for i, (app_id, name, remote) in enumerate(fp_queue, 1):
        log(f"[{i}/{len(fp_queue)}] Flatpak · {name} ({app_id})", end=" ")
        if args.dry_run or flatpak_install(app_id, remote, args.verbose):
            fp_ok.append(app_id)
            installed_fp[app_id] = name
            log("✔", "g")
        else:
            fp_fail.append(f"{name} ({app_id})")
            log("✖", "r")

    # Permisos (mandos/joysticks) para todos los juegos Flatpak instalados
    if not args.dry_run:
        for app_id in installed_fp:
            if app_id in fp_catalog:
                flatpak_grant_permissions(app_id)

    # Claves de todo lo que queda cubierto por Flatpak
    fp_keys = set()
    for app_id, name in installed_fp.items():
        fp_keys |= keys_for(name=name, ident=app_id, kind="flatpak")

    # ---------- 4. Cola DNF ----------
    dnf_ok, dnf_fail = [], []
    if not args.no_dnf and not args.solo_limpiar:
        rpm_games = get_installed_rpm_games(dnf_group, installed_rpms)
        rpm_keys = set().union(*rpm_games.values()) if rpm_games else set()
        dnf_queue = [pkg for pkg in sorted(dnf_group)
                     if pkg not in installed_rpms
                     and not (keys_for(ident=pkg, kind="rpm") & (fp_keys | steam_keys | rpm_keys))]
        log(f"\n[*] Juegos DNF por instalar (sin equivalente Flatpak): {C['b']}{len(dnf_queue)}{C['x']}")
        if dnf_queue and not args.dry_run and not confirm("¿Instalar los juegos DNF pendientes?", args.yes):
            dnf_queue = []
        for i, pkg in enumerate(dnf_queue, 1):
            log(f"[{i}/{len(dnf_queue)}] DNF · {pkg}", end=" ")
            cmd = ["dnf", "install", "-y", pkg]
            rc = 0 if args.dry_run else (run_live(cmd, 1800) if args.verbose else run_cmd(cmd, timeout=1800)[0])
            if rc == 0:
                dnf_ok.append(pkg)
                installed_rpms.add(pkg)
                log("✔", "g")
            else:
                dnf_fail.append(pkg)
                log("✖", "r")

    # ---------- 5. Cola Snap ----------
    snap_ok, snap_fail = [], []
    if sb and snap_catalog and not args.solo_limpiar:
        rpm_games = get_installed_rpm_games(dnf_group, installed_rpms)
        rpm_keys = set().union(*rpm_games.values()) if rpm_games else set()
        for pkg in dnf_ok:  # en simulación aún no existen sus .desktop
            rpm_keys |= keys_for(ident=pkg, kind="rpm")
        snap_queue = [s for s in snap_catalog
                      if s not in installed_snaps
                      and not (keys_for(ident=s, kind="snap") & (fp_keys | rpm_keys | steam_keys))]
        log(f"\n[*] Juegos Snap por instalar (sin equivalente Flatpak ni DNF): {C['b']}{len(snap_queue)}{C['x']}")
        if snap_queue and not args.dry_run and not confirm("¿Instalar los juegos Snap pendientes?", args.yes):
            snap_queue = []
        for i, s in enumerate(snap_queue, 1):
            log(f"[{i}/{len(snap_queue)}] Snap · {s}", end=" ")
            if args.dry_run or snap_install(sb, s, args.verbose):
                if not args.dry_run:
                    snap_grant_permissions(sb, s)
                snap_ok.append(s)
                installed_snaps.add(s)
                log("✔", "g")
            else:
                snap_fail.append(s)
                log("✖", "r")

    # ---------- 6. Eliminar duplicados (Flatpak > DNF > Snap) ----------
    log("\n[*] Buscando juegos duplicados...")
    rpm_games = get_installed_rpm_games(dnf_group, installed_rpms)
    snap_games = get_installed_snap_games(sb, installed_snaps, snap_catalog)
    rpm_keys_all = set()
    remove_rpm, remove_snap, kept_rpm = [], [], []
    for pkg, k in sorted(rpm_games.items()):
        if is_blocked(pkg):
            continue
        if k & fp_keys:
            if rpm_removable(pkg) or args.dry_run:
                remove_rpm.append(pkg)
            else:
                kept_rpm.append(pkg)
        else:
            rpm_keys_all |= k
    for s, k in sorted(snap_games.items()):
        if is_blocked(s):
            continue
        if k & (fp_keys | rpm_keys_all):
            remove_snap.append(s)

    if not remove_rpm and not remove_snap:
        log("    No hay juegos duplicados.", "g")
    else:
        for pkg in remove_rpm:
            log(f"    - [DNF]  {pkg}  → ya existe en Flatpak")
        for s in remove_snap:
            log(f"    - [Snap] {s}  → ya existe en Flatpak/DNF")
        if args.dry_run:
            log("[Simulación] Se eliminarían los duplicados listados.", "y")
        elif confirm("¿Eliminar estos duplicados?", args.yes):
            for s in remove_snap:
                rc = run_cmd([sb, "remove", "--purge", s], timeout=600)[0]
                log(f"    Snap {s}: {'eliminado ✔' if rc == 0 else 'error ✖'}", "g" if rc == 0 else "r")
            for pkg in remove_rpm:
                rc = run_cmd(["dnf", "remove", "-y", pkg], timeout=900)[0]
                log(f"    DNF {pkg}: {'eliminado ✔' if rc == 0 else 'error ✖'}", "g" if rc == 0 else "r")
    for pkg in kept_rpm:
        log(f"    [!] {pkg} está duplicado pero otros paquetes dependen de él; no se elimina.", "y")

    # ---------- 7. Resumen ----------
    log("\n" + "=" * 64, "c")
    if args.dry_run:
        log("RESUMEN (SIMULACIÓN: no se ha cambiado nada)", "b")
        log(f"  Flatpak que se instalarían : {len(fp_ok)}")
        log(f"  DNF que se instalarían     : {len(dnf_ok)}")
        log(f"  Snap que se instalarían    : {len(snap_ok)}")
        log(f"  Duplicados que se quitarían: {len(remove_rpm) + len(remove_snap)}")
    else:
        log("RESUMEN", "b")
        log(f"  Flatpak instalados : {len(fp_ok)}   fallidos: {len(fp_fail)}")
        log(f"  DNF instalados     : {len(dnf_ok)}   fallidos: {len(dnf_fail)}")
        log(f"  Snap instalados    : {len(snap_ok)}   fallidos: {len(snap_fail)}")
        log(f"  Duplicados quitados: {len(remove_rpm) + len(remove_snap)}")
    for f in fp_fail + dnf_fail + snap_fail:
        log(f"   ✖ {f}", "r")
    if LOG_PATH:
        log(f"  Registro: {LOG_PATH}", "d")
    log("=" * 64, "c")

    if sys.stdin.isatty():
        try:
            input("\nPresiona Enter para salir...")
        except (KeyboardInterrupt, EOFError):
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrumpido. Los juegos ya instalados se conservan; puedes volver a ejecutarlo.")
        sys.exit(130)
