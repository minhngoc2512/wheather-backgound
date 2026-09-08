#!/usr/bin/env python3
"""Cua so cai dat cho weather-background.

Cho phep chinh toa do / man hinh / thoi tiet, va chon anh nen that tu
Wikimedia Commons theo chu de thay vi dung 4 anh ve san.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import catalog  # noqa: E402
import wallpaper  # noqa: E402

SETTERS = ("auto", "gnome", "kde", "swaybg", "feh", "none")
PHASE_LABEL = {
    "night": "Night", "dawn": "Dawn", "morning": "Morning",
    "midday": "Midday", "afternoon": "Afternoon",
    "golden_hour": "Golden hour", "dusk": "Dusk", "twilight": "Twilight",
}
SEASON_LABEL = {"": "No season", "spring": "Spring", "summer": "Summer",
                "autumn": "Autumn", "winter": "Winter"}

def bundled_dir() -> Path | None:
    """Thu muc anh di kem goi. Bo qua ung vien dau (thu muc rieng cua user)."""
    for cand in wallpaper.WALLPAPER_CANDIDATES[1:]:
        if wallpaper.has_bases(cand):
            return cand
    return None


USER_CONFIG = wallpaper.XDG_CONFIG / "weather-background" / "config.toml"
USER_WALLPAPERS = wallpaper.XDG_DATA / "weather-background" / "wallpapers"
CREDITS = USER_WALLPAPERS / "credits.txt"


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def read_settings() -> dict:
    path = wallpaper.find_config(None)
    if path is None:
        return {"latitude": 21.0278, "longitude": 105.8342, "setter": "auto",
                "resolution": "2560x1440", "weather": True, "season": "auto"}
    cfg = wallpaper.load_config(path)
    res = f"{cfg.resolution[0]}x{cfg.resolution[1]}" if cfg.resolution else ""
    return {"latitude": cfg.latitude, "longitude": cfg.longitude,
            "setter": cfg.setter, "resolution": res, "weather": cfg.weather,
            "season": cfg.season}


def write_settings(s: dict) -> None:
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG.write_text(
        "# Sinh boi weather-background-settings.\n"
        "# Ghi de config he thong o /etc/xdg/weather-background/config.toml\n\n"
        "[location]\n"
        f"latitude  = {s['latitude']}\n"
        f"longitude = {s['longitude']}\n\n"
        "[display]\n"
        f'setter = "{s["setter"]}"\n'
        f'season = "{s.get("season", "auto")}"\n'
        + (f'resolution = "{s["resolution"]}"\n' if s["resolution"] else "# resolution = \"2560x1440\"\n")
        + "\n[weather]\n"
        f"enabled = {'true' if s['weather'] else 'false'}\n"
    )


# --------------------------------------------------------------------------
# giao dien
# --------------------------------------------------------------------------

class Window(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="Weather Background")
        self.set_default_size(940, 700)
        self.set_border_width(0)

        self.settings = read_settings()
        self.candidates: dict[str, list[catalog.Candidate]] = {}
        self.chosen: dict[str, catalog.Candidate] = {}
        self.flowboxes: dict[str, Gtk.FlowBox] = {}
        self.previews: dict[str, Gtk.Image] = {}
        self.phase_labels: dict[str, Gtk.Label] = {}

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        notebook = Gtk.Notebook()
        notebook.set_border_width(12)
        root.pack_start(notebook, True, True, 0)
        notebook.append_page(self._page_bundled(), Gtk.Label(label="Bundled sets"))
        notebook.append_page(self._page_wallpapers(), Gtk.Label(label="Find online"))
        notebook.append_page(self._page_config(), Gtk.Label(label="Settings"))

        bar = Gtk.Box(spacing=8)
        bar.set_border_width(12)
        self.status = Gtk.Label(label="Ready", xalign=0.0)
        self.status.set_ellipsize(3)                      # PANGO_ELLIPSIZE_END
        bar.pack_start(self.status, True, True, 0)
        apply_btn = Gtk.Button(label="Apply now")
        apply_btn.connect("clicked", self.on_apply)
        bar.pack_end(apply_btn, False, False, 0)
        root.pack_end(bar, False, False, 0)

    # ---- tab bo anh co san ----------------------------------------------
    def _page_bundled(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(12)

        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label="Set:"), False, False, 0)
        self.bundle_combo = Gtk.ComboBoxText()
        self.bundle_combo.append("auto", "Automatic by season")
        for key in wallpaper.SEASONS:
            self.bundle_combo.append(key, SEASON_LABEL[key])
        self.bundle_combo.append("off", "Generated set")
        self.bundle_combo.set_active_id(self.settings.get("season", "auto"))
        self.bundle_combo.connect("changed", lambda _c: self._show_bundle())
        top.pack_start(self.bundle_combo, False, False, 0)

        use = Gtk.Button(label="Use this set")
        use.connect("clicked", self.on_use_bundle)
        top.pack_start(use, False, False, 0)
        box.pack_start(top, False, False, 0)

        self.bundle_note = Gtk.Label(xalign=0.0)
        self.bundle_note.set_line_wrap(True)
        box.pack_start(self.bundle_note, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.bundle_flow = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=4,
                                       selection_mode=Gtk.SelectionMode.NONE,
                                       column_spacing=8, row_spacing=8)
        scroller.add(self.bundle_flow)
        box.pack_start(scroller, True, True, 0)

        self._show_bundle()
        return box

    def _bundle_target(self) -> tuple[Path | None, str | None]:
        """(thu muc, mua) ung voi lua chon dang hien."""
        folder = bundled_dir()
        mode = self.bundle_combo.get_active_id() or "auto"
        if mode == "off":
            return folder, None
        if mode == "auto":
            return folder, wallpaper.current_season(self.settings["latitude"])
        return folder, mode

    def _show_bundle(self) -> None:
        for child in self.bundle_flow.get_children():
            self.bundle_flow.remove(child)

        folder, season = self._bundle_target()
        if folder is None:
            self.bundle_note.set_markup(
                "<i>No bundled set found.</i>")
            self.bundle_flow.show_all()
            return

        notes = [f"<b>Folder:</b> {GLib.markup_escape_text(str(folder))}"
                 + (f"  <b>season:</b> {SEASON_LABEL.get(season, season)}" if season
                    else "  (no season)")]
        # Anh rieng cua user vong uu tien cao hon - phai noi ro, neu khong
        # nguoi dung se doi bo anh ma khong thay gi thay doi.
        if wallpaper.has_bases(USER_WALLPAPERS):
            notes.append(
                "<span foreground='#c04000'>You have custom images in "
                f"{GLib.markup_escape_text(str(USER_WALLPAPERS))} — those take "
                "priority over bundled sets, so changing the set here will have "
                "no effect until you remove them.</span>")
        self.bundle_note.set_markup("\n".join(notes))

        for phase in wallpaper.PHASES:
            try:
                path = wallpaper.find_base(folder, phase, season)
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 210, 118, True)
            except (FileNotFoundError, GLib.Error):
                continue
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            cell.pack_start(Gtk.Image.new_from_pixbuf(pix), False, False, 0)
            cap = Gtk.Label(xalign=0.0)
            cap.set_markup(f"<small>{PHASE_LABEL[phase]}</small>")
            cell.pack_start(cap, False, False, 0)
            self.bundle_flow.add(cell)
        self.bundle_flow.show_all()

    def on_use_bundle(self, _btn: Gtk.Button) -> None:
        mode = self.bundle_combo.get_active_id() or "auto"
        self.settings["season"] = mode
        try:
            write_settings(self.settings)
        except OSError as exc:
            self.say(f"Cannot write config: {exc}")
            return
        if hasattr(self, "season_cfg_combo"):
            self.season_cfg_combo.set_active_id(mode)
        self.say(f"Season set to \"{mode}\". Click 'Apply now' to update the wallpaper.")

    # ---- tab anh nen ----------------------------------------------------
    def _page_wallpapers(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(12)

        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label="Theme:"), False, False, 0)
        self.theme_combo = Gtk.ComboBoxText()
        for key, (label, _) in catalog.THEMES.items():
            self.theme_combo.append(key, label)
        self.theme_combo.set_active_id(catalog.DEFAULT_THEME)
        top.pack_start(self.theme_combo, False, False, 0)

        search_btn = Gtk.Button(label="Search")
        search_btn.connect("clicked", self.on_search)
        top.pack_start(search_btn, False, False, 0)

        note = Gtk.Label(xalign=0.0)
        note.set_markup(
            "<small>Images from Wikimedia Commons. Credits are saved to "
            "credits.txt next to them.</small>")
        top.pack_end(note, False, False, 0)
        box.pack_start(top, False, False, 0)

        pick = Gtk.Box(spacing=8)
        pick.pack_start(Gtk.Label(label="Time of day:"), False, False, 0)
        self.phase_combo = Gtk.ComboBoxText()
        for ph in wallpaper.PHASES:
            self.phase_combo.append(ph, PHASE_LABEL[ph])
        self.phase_combo.set_active_id(wallpaper.PHASES[0])
        self.phase_combo.connect(
            "changed", lambda c: self.stack.set_visible_child_name(c.get_active_id()))
        pick.pack_start(self.phase_combo, False, False, 0)

        pick.pack_start(Gtk.Label(label="   Season:"), False, False, 0)
        self.season_combo = Gtk.ComboBoxText()
        for key, label in SEASON_LABEL.items():
            self.season_combo.append(key or "none", label)
        self.season_combo.set_active_id("none")
        self.season_combo.connect("changed", self.on_season_changed)
        pick.pack_start(self.season_combo, False, False, 0)
        box.pack_start(pick, False, False, 0)

        self.stack = Gtk.Stack()
        box.pack_start(self.stack, True, True, 0)

        for phase in wallpaper.PHASES:
            self.stack.add_titled(self._phase_pane(phase), phase, PHASE_LABEL[phase])
        return box

    def _phase_pane(self, phase: str) -> Gtk.Widget:
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        current = Gtk.Box(spacing=10)
        img = Gtk.Image()
        self.previews[phase] = img
        current.pack_start(img, False, False, 0)
        lbl = Gtk.Label(xalign=0.0, yalign=0.0)
        lbl.set_line_wrap(True)
        current.pack_start(lbl, True, True, 0)
        pane.pack_start(current, False, False, 0)
        self.phase_labels[phase] = lbl
        self._refresh_preview(phase, lbl)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        flow = Gtk.FlowBox(valign=Gtk.Align.START, max_children_per_line=4,
                           selection_mode=Gtk.SelectionMode.SINGLE,
                           column_spacing=8, row_spacing=8)
        flow.connect("child-activated", self.on_pick, phase)
        self.flowboxes[phase] = flow
        scroller.add(flow)
        pane.pack_start(scroller, True, True, 0)

        use_btn = Gtk.Button(label=f"Use for {PHASE_LABEL[phase].lower()}")
        use_btn.connect("clicked", self.on_use, phase, lbl)
        pane.pack_start(use_btn, False, False, 0)
        return pane

    def target_dir(self) -> Path:
        season = self.season_combo.get_active_id() if hasattr(self, "season_combo") else "none"
        return USER_WALLPAPERS if season in (None, "none") else USER_WALLPAPERS / season

    def on_season_changed(self, _combo: Gtk.ComboBoxText) -> None:
        for phase, label in self.phase_labels.items():
            self._refresh_preview(phase, label)

    def _refresh_preview(self, phase: str, label: Gtk.Label) -> None:
        try:
            path = wallpaper.find_base(self.target_dir(), phase)
        except FileNotFoundError:
            self.previews[phase].clear()
            label.set_markup("<i>No custom image — using the bundled default.</i>")
            return
        pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 240, 135, True)
        self.previews[phase].set_from_pixbuf(pix)
        label.set_markup(f"<b>Currently using:</b> {GLib.markup_escape_text(path.name)}")

    # ---- tab cau hinh ---------------------------------------------------
    def _page_config(self) -> Gtk.Widget:
        grid = Gtk.Grid(row_spacing=10, column_spacing=12)
        grid.set_border_width(12)
        s = self.settings

        def row(n: int, text: str, widget: Gtk.Widget, hint: str = "") -> None:
            grid.attach(Gtk.Label(label=text, xalign=1.0), 0, n, 1, 1)
            grid.attach(widget, 1, n, 1, 1)
            if hint:
                h = Gtk.Label(xalign=0.0)
                h.set_markup(f"<small>{hint}</small>")
                grid.attach(h, 2, n, 1, 1)

        self.lat = Gtk.SpinButton.new_with_range(-90, 90, 0.0001)
        self.lat.set_digits(4); self.lat.set_value(s["latitude"])
        self.lon = Gtk.SpinButton.new_with_range(-180, 180, 0.0001)
        self.lon.set_digits(4); self.lon.set_value(s["longitude"])
        self.res = Gtk.Entry(text=s["resolution"])
        self.res.set_placeholder_text("2560x1440 - leave empty to keep the source size")
        self.setter = Gtk.ComboBoxText()
        for x in SETTERS:
            self.setter.append(x, x)
        self.setter.set_active_id(s["setter"] if s["setter"] in SETTERS else "auto")
        self.weather = Gtk.Switch(halign=Gtk.Align.START, active=s["weather"])
        self.season_cfg_combo = Gtk.ComboBoxText()
        self.season_cfg_combo.append("auto", "Automatic by season")
        for key in wallpaper.SEASONS:
            self.season_cfg_combo.append(key, SEASON_LABEL[key])
        self.season_cfg_combo.append("off", "No season")
        self.season_cfg_combo.set_active_id(s.get("season", "auto"))

        row(0, "Latitude:", self.lat, "Used for sun angle and weather lookup")
        row(1, "Longitude:", self.lon)
        row(2, "Resolution:", self.res)
        row(3, "Wallpaper setter:", self.setter, "auto = detect the running desktop")
        row(4, "Seasonal set:", self.season_cfg_combo, "Same value as the 'Bundled sets' tab")
        row(5, "Weather effects:", self.weather, "Off = follow the sun only, no network")

        save = Gtk.Button(label="Save settings")
        save.connect("clicked", self.on_save)
        grid.attach(save, 1, 6, 1, 1)

        path_lbl = Gtk.Label(xalign=0.0)
        path_lbl.set_markup(f"<small>Written to <tt>{USER_CONFIG}</tt></small>")
        grid.attach(path_lbl, 1, 7, 2, 1)
        return grid

    # ---- hanh dong ------------------------------------------------------
    def say(self, text: str) -> None:
        GLib.idle_add(self.status.set_text, text)

    def on_search(self, _btn: Gtk.Button) -> None:
        theme = self.theme_combo.get_active_id()
        phase = self.stack.get_visible_child_name()
        self.say(f"Searching for {PHASE_LABEL[phase].lower()} images…")
        threading.Thread(target=self._search_worker, args=(theme, phase), daemon=True).start()

    def _search_worker(self, theme: str, phase: str) -> None:
        try:
            found = catalog.search(theme, phase, limit=14)
        except catalog.RateLimited as exc:
            self.say(str(exc))
            return
        except OSError as exc:
            self.say(f"Cannot reach Wikimedia Commons: {exc}")
            return
        except Exception as exc:
            self.say(f"Search failed: {exc}")
            return
        if not found:
            self.say("No suitable images found.")
            return

        GLib.idle_add(self._clear_flow, phase)
        kept = 0
        for cand in found:
            try:
                data = catalog.fetch(cand.thumb_url, timeout=30)
            except Exception:
                continue
            if not catalog.is_photo(data):        # loai ban khac / anh ve tinh
                continue
            kept += 1
            GLib.idle_add(self._append_cell, phase, cand, data)
            self.say(f"Loading… {kept} images")
        self.say(f"{kept} images for {PHASE_LABEL[phase].lower()}. Click one to select it.")

    def _clear_flow(self, phase: str) -> None:
        self.candidates[phase] = []
        flow = self.flowboxes[phase]
        for child in flow.get_children():
            flow.remove(child)

    def _append_cell(self, phase: str, cand: catalog.Candidate, data: bytes) -> None:
        loader = GdkPixbuf.PixbufLoader()
        try:
            loader.write(data)
            loader.close()
        except GLib.Error:
            return
        # Them vao danh sach o day (main thread) de thu tu luon khop voi luoi.
        self.candidates.setdefault(phase, []).append(cand)

        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cell.pack_start(Gtk.Image.new_from_pixbuf(loader.get_pixbuf()), False, False, 0)
        cap = Gtk.Label(xalign=0.0)
        cap.set_max_width_chars(30)
        cap.set_ellipsize(3)
        cap.set_markup(f"<small>{GLib.markup_escape_text(cand.license)} - "
                       f"{cand.width}x{cand.height}</small>")
        cell.pack_start(cap, False, False, 0)
        self.flowboxes[phase].add(cell)
        self.flowboxes[phase].show_all()

    def on_pick(self, _flow: Gtk.FlowBox, child: Gtk.FlowBoxChild, phase: str) -> None:
        found = self.candidates.get(phase, [])
        idx = child.get_index()
        if idx < len(found):
            self.chosen[phase] = found[idx]
            self.say(f"Selected: {found[idx].label[:60]}")

    def on_use(self, _btn: Gtk.Button, phase: str, label: Gtk.Label) -> None:
        cand = self.chosen.get(phase)
        if cand is None:
            self.say("Nothing selected. Click an image in the grid first.")
            return
        self.say(f"Downloading {PHASE_LABEL[phase].lower()} image…")
        threading.Thread(target=self._download_worker, args=(cand, phase, label),
                         daemon=True).start()

    def _download_worker(self, cand: catalog.Candidate, phase: str,
                         label: Gtk.Label) -> None:
        try:
            width = 2560
            res = self.settings.get("resolution") or ""
            if "x" in res:
                width = int(res.split("x")[0])
            url = catalog.scaled_url(cand.title, width)
            data = catalog.fetch(url)
            target = self.target_dir()
            target.mkdir(parents=True, exist_ok=True)
            for old in target.glob(f"{phase}.*"):
                old.unlink()
            (target / f"{phase}.jpg").write_bytes(data)
            self._write_credit(phase, cand)
        except catalog.RateLimited as exc:
            self.say(str(exc))
            return
        except Exception as exc:
            self.say(f"Download failed: {exc}")
            return
        GLib.idle_add(self._refresh_preview, phase, label)
        self.say(f"Done: {phase}.jpg ({len(data)//1024} KB). Click 'Apply now' to update.")

    def _write_credit(self, phase: str, cand: catalog.Candidate) -> None:
        lines = []
        if CREDITS.exists():
            lines = [l for l in CREDITS.read_text().splitlines()
                     if not l.startswith(f"{phase}\t")]
        lines.append(f"{phase}\t{cand.label}\t{cand.artist}\t{cand.license}\t{cand.page_url}")
        CREDITS.write_text(
            "# phase\ttitle\tauthor\tlicense\tsource\n"
            + "\n".join(l for l in lines if not l.startswith("#")) + "\n")

    def on_save(self, _btn: Gtk.Button) -> None:
        self.settings = {
            "latitude": round(self.lat.get_value(), 4),
            "longitude": round(self.lon.get_value(), 4),
            "resolution": self.res.get_text().strip(),
            "setter": self.setter.get_active_id(),
            "weather": self.weather.get_active(),
            "season": self.season_cfg_combo.get_active_id() or "auto",
        }
        try:
            write_settings(self.settings)
        except OSError as exc:
            self.say(f"Cannot write config: {exc}")
            return
        if hasattr(self, "bundle_combo"):
            self.bundle_combo.set_active_id(self.settings["season"])
        self.say(f"Saved {USER_CONFIG}")

    def on_apply(self, _btn: Gtk.Button) -> None:
        self.say("Updating wallpaper…")
        threading.Thread(target=self._apply_worker, daemon=True).start()

    def _apply_worker(self) -> None:
        exe = "/usr/bin/weather-wallpaper"
        cmd = [exe] if Path(exe).exists() else [
            sys.executable, str(Path(__file__).resolve().parent / "wallpaper.py")]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as exc:
            self.say(f"Run failed: {exc}")
            return
        out = (r.stdout or r.stderr or "").strip().splitlines()
        self.say(out[-1] if out else "Done.")


USAGE = """weather-background-settings - settings window for weather-background

Takes no arguments other than --help. Wallpaper options live on the
weather-wallpaper command (see `weather-wallpaper --help`).
"""


def main() -> int:
    if len(sys.argv) > 1:
        if sys.argv[1] in ("-h", "--help"):
            print(USAGE, end="")
            return 0
        print(f"Unknown argument: {sys.argv[1]}\n", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2

    win = Window()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
