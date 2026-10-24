# 🎮 Instalar Juegos — instalador de juegos para Fedora sin duplicados

Script en Python para **Fedora (KDE Plasma / Discover)** que instala de forma masiva los juegos nativos de Linux disponibles en **Flatpak (Flathub)**, el **grupo `games` de DNF** y la **sección de juegos de Snap**, garantizando que **cada juego quede instalado una sola vez** y respetando un orden de preferencia de formatos:

```
Flatpak  >  DNF (RPM)  >  Snap
```

Además **nunca instala Steam ni plataformas para ejecutar juegos de Windows** (Wine, Proton, Lutris, Bottles, Heroic, PlayOnLinux…), y elimina los duplicados que ya tengas instalados.

> ⚠️ **Aviso importante:** el script está pensado para instalar *todo* el catálogo de juegos disponible. Eso son cientos (o miles) de paquetes y puede ocupar **cientos de GB** y tardar horas. Ejecuta primero el modo `--dry-run` para ver qué haría.

---

## Índice

1. [Características](#características)
2. [Requisitos](#requisitos)
3. [Instalación](#instalación)
4. [Uso](#uso)
5. [Cómo funciona (paso a paso)](#cómo-funciona-paso-a-paso)
6. [Detección de duplicados](#detección-de-duplicados)
7. [Lista negra: Steam y plataformas de Windows](#lista-negra-steam-y-plataformas-de-windows)
8. [Permisos que concede](#permisos-que-concede)
9. [Registro (log)](#registro-log)
10. [Estructura del repositorio](#estructura-del-repositorio)
11. [Limitaciones conocidas](#limitaciones-conocidas)
12. [Licencia](#licencia)

---

## Características

- ✅ **Prioridad de formatos** Flatpak > DNF > Snap: un juego que existe en Flatpak no se instala por DNF ni Snap; uno que existe en DNF no se instala por Snap.
- ✅ **Limpieza de duplicados ya instalados**: conserva la versión Flatpak; si no la hay, conserva la de DNF y quita la de Snap.
- ✅ **Respeta tu biblioteca de Steam**: si ya tienes un juego en Steam, no instala otra copia (Steam se lee, pero nunca se instala).
- ✅ **Bloqueo de Steam y capas de compatibilidad con Windows**.
- ✅ **Permisos para mandos**: acceso a dispositivos (`--device=all`) en los Flatpak y conexión automática de las interfaces Snap.
- ✅ **Modo simulación** (`--dry-run`) que no toca nada y no pide contraseña.
- ✅ **Confirmación antes de cada fase** (o `--yes` para modo desatendido).
- ✅ **Seguro de interrumpir**: con `Ctrl+C` se conserva lo ya instalado y puedes volver a lanzarlo; retoma donde lo dejó porque salta lo instalado.
- ✅ **Lanzador `.desktop`** con acciones rápidas en el menú contextual de KDE.
- ✅ Sin dependencias externas: solo la biblioteca estándar de Python 3.

## Requisitos

| Requisito | Notas |
|---|---|
| Fedora (probado en Fedora 44, KDE) | Usa `dnf` (compatible con dnf4 y dnf5) y `rpm`. |
| Python 3 | Viene con Fedora. |
| Privilegios de administrador | El script se relanza solo con `sudo` o `pkexec` si hace falta. |
| `konsole` | Solo para el lanzador `.desktop`. El script funciona en cualquier terminal. |
| Conexión a Internet | Para descargar catálogos y juegos. |

`flatpak` y `snapd` se instalan automáticamente si faltan (snapd solo si no usas `--no-snap` / `--no-snapd-install`).

## Instalación

```bash
git clone https://github.com/riqgonzalo-lgtm/install-games.git
cd install-games
./install.sh
```

`install.sh` (no necesita sudo):

- copia el script a `~/.local/share/install-games/install_games.py`;
- genera el lanzador `~/.local/share/applications/install_games.desktop` con la ruta correcta;
- tras esto aparece **«Instalar Juegos»** en el menú de aplicaciones de KDE.

Para quitarlo: `./uninstall.sh` (solo borra el script y el lanzador; **no** desinstala juegos).

También puedes ejecutarlo directamente sin instalar nada: `python3 install_games.py --dry-run`.

## Uso

```bash
python3 install_games.py [opciones]
```

| Opción | Efecto |
|---|---|
| *(sin opciones)* | Modo interactivo: pide confirmación antes de cada fase. |
| `--dry-run` | Simulación. Muestra lo que haría sin cambiar nada. No requiere root. |
| `-y`, `--yes` | No pregunta nada (desatendido). |
| `--no-dnf` | No instala juegos desde DNF. |
| `--no-snap` | No usa Snap en absoluto. |
| `--no-snapd-install` | Usa Snap solo si `snapd` ya está instalado; no lo instala. |
| `--solo-limpiar` | No instala nada: solo busca y elimina duplicados. |
| `--verbose` | Muestra la salida completa de `flatpak` / `dnf` / `snap`. |

### Acciones del lanzador (clic derecho en «Instalar Juegos»)

| Acción | Comando ejecutado |
|---|---|
| Abrir (clic normal) | `sudo python3 install_games.py` |
| Simular (no cambia nada) | `python3 install_games.py --dry-run` |
| Solo quitar juegos duplicados | `sudo python3 install_games.py --solo-limpiar` |
| Instalar sin usar Snap | `sudo python3 install_games.py --no-snap` |

Todas se abren en `konsole --hold`, de modo que la ventana no se cierra al terminar y puedes leer el resumen.

---

## Cómo funciona (paso a paso)

El programa (`main()`) se divide en 7 fases.

### 0. Arranque y privilegios

- `ensure_root()`: si no es root (y no es `--dry-run`), se **relanza a sí mismo** con `sudo` (o `pkexec` si no hay sudo) mediante `os.execvp`, conservando los argumentos.
- `real_user_info()`: averigua el **usuario real** que lanzó el script (a partir de `SUDO_USER` o `PKEXEC_UID`) y su carpeta personal. Se usa para leer sus Flatpak de usuario, su biblioteca de Steam y guardar el log en su `$HOME` con él como propietario.
- Abre el archivo de registro `~/install_games.log` (excepto en simulación).

### 1. Preparación

- **Flatpak** (`flatpak_prepare`): instala `flatpak` con DNF si falta, añade el remoto **Flathub** a nivel de sistema, lo habilita y le quita el filtro (Fedora a veces lo trae filtrado o deshabilitado) y actualiza los metadatos **AppStream** para tener el catálogo al día.
- **Snap** (`ensure_snapd`): si se va a usar Snap, comprueba `snapd`; si falta lo instala con DNF, activa `snapd.socket`, crea el enlace `/snap → /var/lib/snapd/snap` (necesario para snaps *classic* en Fedora) y espera a que snapd termine de inicializarse (`snap wait system seed.loaded`).

### 2. Inventario

Lee los catálogos disponibles y lo que ya está instalado:

| Fuente | Cómo se obtiene |
|---|---|
| Catálogo Flatpak de juegos | Parsea en streaming (`ET.iterparse`) los `appstream.xml(.gz)` locales en `/var/lib/flatpak/appstream/<remoto>/<arch>/active/` y se queda con los componentes de categoría `Game` que son aplicaciones (`app/…`). Si hay Flathub y otro remoto con el mismo ID, prefiere Flathub. **Respaldo:** si obtiene menos de 50 juegos, consulta la API pública `flathub.org/api/v2/collection/category/Game` paginando de 250 en 250. |
| Grupo de juegos DNF | `dnf group info games` con `LC_ALL=C` y un parser tolerante a los formatos de dnf4 y dnf5. |
| Juegos Snap | `snap find --section=games`. |
| Flatpak instalados | `flatpak list --app` (como el usuario real y como root, para ver instalaciones de sistema y de usuario). |
| RPM instalados | `rpm -qa`. |
| Snap instalados | `snap list`. |
| Biblioteca de Steam | Lee los `appmanifest_*.acf` de `~/.local/share/Steam/steamapps` y de la versión Flatpak de Steam, extrayendo el nombre de cada juego. |

A todos los catálogos se les aplica la **lista negra** (ver más abajo) y se muestra un recuento.

### 3. Cola Flatpak

Para cada juego del catálogo (ordenado alfabéticamente) se añade a la cola si **no está instalado** y **no está ya en tu biblioteca de Steam**. Tras confirmar, se instala uno a uno con:

```
flatpak install --system -y --noninteractive <remoto> <app_id>
```

Si falla, reintenta con `flathub` explícito y luego sin remoto. Al terminar concede `--device=all` a todos los juegos Flatpak instalados y calcula las **claves Flatpak** (`fp_keys`): el conjunto de nombres normalizados de todo lo que ya cubre Flatpak.

### 4. Cola DNF

Se encolan los paquetes del grupo `games` que:

- no están instalados como RPM, y
- **no coinciden** con ninguna clave de Flatpak, de Steam ni de un juego RPM ya instalado.

Se instalan con `dnf install -y <paquete>` (timeout de 30 min por paquete).

### 5. Cola Snap

Igual, pero solo entran los snaps de la sección de juegos que **no coinciden** con nada de Flatpak, DNF (incluidos los recién instalados) ni Steam. Antes de instalar se consulta `snap info` y, si el snap usa confinamiento *classic*, se añade `--classic`. Tras instalar, se conectan sus interfaces pendientes (`snap connect`).

### 6. Eliminación de duplicados

- Recorre los juegos RPM instalados (detectados por sus `.desktop` con categoría `Game` en `/usr/share/applications`, más los del grupo `games`). Si alguno **coincide con un Flatpak**, se marca para eliminar, salvo que `rpm -e --test` indique que otros paquetes dependen de él (entonces se conserva y se avisa).
- Recorre los juegos Snap instalados (`.desktop` en `/var/lib/snapd/desktop/applications` y snaps del catálogo de juegos). Si coincide con un Flatpak o con un RPM que se conserva, se marca para eliminar.
- Muestra la lista y, tras confirmar, ejecuta `snap remove --purge` y `dnf remove -y`.

Los programas de la lista negra nunca se tocan en esta fase.

### 7. Resumen

Muestra cuántos juegos se instalaron y fallaron por cada formato, cuántos duplicados se quitaron, la lista de fallos y la ruta del log. Si hay terminal interactiva, espera a que pulses Enter.

---

## Detección de duplicados

El mismo juego tiene nombres distintos en cada formato (p. ej. `org.supertuxproject.SuperTux`, `supertux` y `SuperTux`). Para compararlos, `keys_for()` genera un **conjunto de claves normalizadas** por juego:

1. Se pasa a minúsculas y se eliminan todos los caracteres que no sean `a-z0-9` (`norm()`): `"Super Tux!"` → `supertux`.
2. **Flatpak / `.desktop`**: se usa el último segmento del ID (`org.supertuxproject.SuperTux` → `supertux`).
3. **RPM / Snap**: el nombre del paquete completo y una versión sin prefijos típicos (`gnome-`, `kde-`, `xfce4-`, `mate-`, `gtk-`, `qt-`, `sdl-`, `python3-`) ni sufijos (`-game(s)`, `-gtk`, `-qt`, `-sdl(2)`, `-bin`, `-git`). Así `gnome-mines` → `mines`.
4. Se añade también el nombre visible (campo `Name=` del `.desktop` o `<name>` de AppStream).
5. Se descartan claves de **menos de 3 caracteres** para evitar falsos positivos.

Dos juegos se consideran el mismo si **comparten al menos una clave**.

## Lista negra: Steam y plataformas de Windows

`is_blocked()` descarta un elemento si cumple cualquiera de estas reglas:

- **Prefijo de ID** conocido: `com.valvesoftware.`, `org.winehq.`, `com.usebottles.`, `net.lutris.`, `com.heroicgameslauncher.`, `com.playonlinux.`, `org.phoenicis.`, `io.github.faugus.`, ProtonUp-Qt, ProtonPlus, Protontricks, Minigalaxy, GameHub, Rare, Legendary, Steam ROM Manager, BoilR, Vinegar…
- **Segmento exacto** del ID o nombre de paquete (separado por `.`, `-`, `_`…): `steam`, `wine`, `winetricks`, `proton`, `lutris`, `bottles`, `heroic`, `crossover`, `dxvk`, `vkd3d`, `umu`, etc.
- **Expresión regular** sobre el nombre visible: `Steam`, `Wine…`, `Lutris`, `Bottles`, `PlayOnLinux`, `Heroic Games`, `Proton…`, `CrossOver`…

Se comparan segmentos completos, no subcadenas, para no bloquear por error juegos cuyo nombre contenga esas letras (p. ej. «steampunk» o «twine» no se bloquean por el ID).

## Permisos que concede

- **Flatpak:** `flatpak override --system --device=all <app>` en cada juego Flatpak instalado, para que detecte mandos, joysticks y volantes.
- **Snap:** para cada snap instalado, todas las conexiones que aparecen sin conectar en `snap connections` se conectan con `snap connect`.

## Registro (log)

Todo lo que se muestra en pantalla se guarda también (sin códigos de color) en `~/install_games.log`, con una cabecera de fecha y hora por ejecución. El archivo pertenece a tu usuario aunque el script se ejecute como root. En `--dry-run` no se escribe log.

## Estructura del repositorio

```
install-games/
├── install_games.py          # El script principal
├── install_games.desktop.in  # Plantilla del lanzador de KDE (@SCRIPT_PATH@ se sustituye al instalar)
├── install.sh                # Instala script + lanzador en ~/.local/share
├── uninstall.sh              # Quita script + lanzador
├── LICENSE                   # MIT
└── README.md
```

## Limitaciones conocidas

- **Espacio y tiempo:** instalar el catálogo completo es enorme. Usa `--dry-run` primero y responde «n» en las fases que no quieras.
- **Comparación por nombre:** la detección de duplicados es heurística. Dos juegos distintos con nombres muy parecidos podrían tratarse como el mismo, y un mismo juego con nombres muy distintos en cada formato podría no detectarse.
- Las claves de Flatpak incluyen **todas** las apps Flatpak instaladas (no solo juegos), lo que puede producir algún falso positivo raro.
- Pensado para Fedora: depende de `dnf`, `rpm` y de las rutas de Flatpak/Snap en Fedora.
- El lanzador usa `konsole`; en otros escritorios cambia `konsole --hold -e` por tu terminal en `install_games.desktop.in`.

## Licencia

[MIT](LICENSE)
