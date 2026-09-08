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
PHASE_LABEL = {"night": "Dem", "dawn": "Binh minh", "day": "Ban ngay", "dusk": "Hoang hon"}

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
                "resolution": "2560x1440", "weather": True}
    cfg = wallpaper.load_config(path)
    res = f"{cfg.resolution[0]}x{cfg.resolution[1]}" if cfg.resolution else ""
    return {"latitude": cfg.latitude, "longitude": cfg.longitude,
            "setter": cfg.setter, "resolution": res, "weather": cfg.weather}


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

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        notebook = Gtk.Notebook()
        notebook.set_border_width(12)
        root.pack_start(notebook, True, True, 0)
        notebook.append_page(self._page_wallpapers(), Gtk.Label(label="Anh nen"))
        notebook.append_page(self._page_config(), Gtk.Label(label="Cau hinh"))

        bar = Gtk.Box(spacing=8)
        bar.set_border_width(12)
        self.status = Gtk.Label(label="San sang", xalign=0.0)
        self.status.set_ellipsize(3)                      # PANGO_ELLIPSIZE_END
        bar.pack_start(self.status, True, True, 0)
        apply_btn = Gtk.Button(label="Ap dung ngay")
        apply_btn.connect("clicked", self.on_apply)
        bar.pack_end(apply_btn, False, False, 0)
        root.pack_end(bar, False, False, 0)

    # ---- tab anh nen ----------------------------------------------------
    def _page_wallpapers(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(12)

        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label="Chu de:"), False, False, 0)
        self.theme_combo = Gtk.ComboBoxText()
        for key, (label, _) in catalog.THEMES.items():
            self.theme_combo.append(key, label)
        self.theme_combo.set_active_id(catalog.DEFAULT_THEME)
        top.pack_start(self.theme_combo, False, False, 0)

        search_btn = Gtk.Button(label="Tim anh")
        search_btn.connect("clicked", self.on_search)
        top.pack_start(search_btn, False, False, 0)

        note = Gtk.Label(xalign=0.0)
        note.set_markup(
            "<small>Anh tu Wikimedia Commons. Ghi cong duoc luu vao credits.txt "
            "canh anh.</small>")
        top.pack_end(note, False, False, 0)
        box.pack_start(top, False, False, 0)

        self.stack = Gtk.Stack()
        switcher = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.CENTER)
        box.pack_start(switcher, False, False, 0)
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

        use_btn = Gtk.Button(label=f"Dat lam anh {PHASE_LABEL[phase].lower()}")
        use_btn.connect("clicked", self.on_use, phase, lbl)
        pane.pack_start(use_btn, False, False, 0)
        return pane

    def _refresh_preview(self, phase: str, label: Gtk.Label) -> None:
        try:
            path = wallpaper.find_base(USER_WALLPAPERS, phase)
        except FileNotFoundError:
            self.previews[phase].clear()
            label.set_markup("<i>Chua co anh rieng - dang dung anh mac dinh cua goi.</i>")
            return
        pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 240, 135, True)
        self.previews[phase].set_from_pixbuf(pix)
        label.set_markup(f"<b>Dang dung:</b> {GLib.markup_escape_text(path.name)}")

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
        self.res.set_placeholder_text("2560x1440 - de trong de giu kich thuoc anh goc")
        self.setter = Gtk.ComboBoxText()
        for x in SETTERS:
            self.setter.append(x, x)
        self.setter.set_active_id(s["setter"] if s["setter"] in SETTERS else "auto")
        self.weather = Gtk.Switch(halign=Gtk.Align.START, active=s["weather"])

        row(0, "Vi do:", self.lat, "Dung de tinh goc mat troi va lay thoi tiet")
        row(1, "Kinh do:", self.lon)
        row(2, "Do phan giai:", self.res)
        row(3, "Cach dat hinh nen:", self.setter, "auto = tu do theo desktop dang chay")
        row(4, "Bat thoi tiet:", self.weather, "Tat = chi doi anh theo mat troi, khong goi mang")

        save = Gtk.Button(label="Luu cau hinh")
        save.connect("clicked", self.on_save)
        grid.attach(save, 1, 5, 1, 1)

        path_lbl = Gtk.Label(xalign=0.0)
        path_lbl.set_markup(f"<small>Ghi vao <tt>{USER_CONFIG}</tt></small>")
        grid.attach(path_lbl, 1, 6, 2, 1)
        return grid

    # ---- hanh dong ------------------------------------------------------
    def say(self, text: str) -> None:
        GLib.idle_add(self.status.set_text, text)

    def on_search(self, _btn: Gtk.Button) -> None:
        theme = self.theme_combo.get_active_id()
        phase = self.stack.get_visible_child_name()
        self.say(f"Dang tim anh {PHASE_LABEL[phase].lower()}...")
        threading.Thread(target=self._search_worker, args=(theme, phase), daemon=True).start()

    def _search_worker(self, theme: str, phase: str) -> None:
        try:
            found = catalog.search(theme, phase, limit=14)
        except catalog.RateLimited as exc:
            self.say(str(exc))
            return
        except OSError as exc:
            self.say(f"Khong ket noi duoc Wikimedia Commons: {exc}")
            return
        except Exception as exc:
            self.say(f"Loi tim kiem: {exc}")
            return
        if not found:
            self.say("Khong tim thay anh nao phu hop.")
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
            self.say(f"Dang tai... {kept} anh")
        self.say(f"{kept} anh cho {PHASE_LABEL[phase].lower()}. Bam vao mot anh de chon.")

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
            self.say(f"Da chon: {found[idx].label[:60]}")

    def on_use(self, _btn: Gtk.Button, phase: str, label: Gtk.Label) -> None:
        cand = self.chosen.get(phase)
        if cand is None:
            self.say("Chua chon anh nao. Bam vao mot anh trong luoi truoc.")
            return
        self.say(f"Dang tai anh {PHASE_LABEL[phase].lower()}...")
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
            USER_WALLPAPERS.mkdir(parents=True, exist_ok=True)
            for old in USER_WALLPAPERS.glob(f"{phase}.*"):
                old.unlink()
            (USER_WALLPAPERS / f"{phase}.jpg").write_bytes(data)
            self._write_credit(phase, cand)
        except catalog.RateLimited as exc:
            self.say(str(exc))
            return
        except Exception as exc:
            self.say(f"Tai that bai: {exc}")
            return
        GLib.idle_add(self._refresh_preview, phase, label)
        self.say(f"Xong: {phase}.jpg ({len(data)//1024} KB). Bam 'Ap dung ngay' de doi hinh nen.")

    def _write_credit(self, phase: str, cand: catalog.Candidate) -> None:
        lines = []
        if CREDITS.exists():
            lines = [l for l in CREDITS.read_text().splitlines()
                     if not l.startswith(f"{phase}\t")]
        lines.append(f"{phase}\t{cand.label}\t{cand.artist}\t{cand.license}\t{cand.page_url}")
        CREDITS.write_text(
            "# phase\ttieu de\ttac gia\tgiay phep\tnguon\n"
            + "\n".join(l for l in lines if not l.startswith("#")) + "\n")

    def on_save(self, _btn: Gtk.Button) -> None:
        self.settings = {
            "latitude": round(self.lat.get_value(), 4),
            "longitude": round(self.lon.get_value(), 4),
            "resolution": self.res.get_text().strip(),
            "setter": self.setter.get_active_id(),
            "weather": self.weather.get_active(),
        }
        try:
            write_settings(self.settings)
        except OSError as exc:
            self.say(f"Khong ghi duoc config: {exc}")
            return
        self.say(f"Da luu {USER_CONFIG}")

    def on_apply(self, _btn: Gtk.Button) -> None:
        self.say("Dang cap nhat hinh nen...")
        threading.Thread(target=self._apply_worker, daemon=True).start()

    def _apply_worker(self) -> None:
        exe = "/usr/bin/weather-wallpaper"
        cmd = [exe] if Path(exe).exists() else [
            sys.executable, str(Path(__file__).resolve().parent / "wallpaper.py")]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as exc:
            self.say(f"Chay that bai: {exc}")
            return
        out = (r.stdout or r.stderr or "").strip().splitlines()
        self.say(out[-1] if out else "Xong.")


USAGE = """weather-background-settings - cua so cai dat cho weather-background

Khong co tham so nao ngoai --help. Cac tuy chon chay hinh nen nam o lenh
weather-wallpaper (xem `weather-wallpaper --help`).
"""


def main() -> int:
    if len(sys.argv) > 1:
        if sys.argv[1] in ("-h", "--help"):
            print(USAGE, end="")
            return 0
        print(f"Tham so khong hop le: {sys.argv[1]}\n", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2

    win = Window()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
