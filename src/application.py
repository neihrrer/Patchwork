import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")

from gi.repository import GLib, Gio, Gtk, Adw, Gdk
from pathlib import Path
from window import QmicWindow, _find_ui_file


class QmicApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.qmic.app",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._window = None

        GLib.set_application_name("Ring")
        GLib.set_prgname("ring")

        self.set_resource_base_path("/org/qmic/app")

        self._setup_actions()

    def _load_css(self):
        css_paths = [
            Path(__file__).parent / "style.css",
            Path(__file__).parent.parent / "build" / "resources" / "style.css",
            Path("/app/share/qmic") / "style.css",
        ]
        provider = Gtk.CssProvider()
        for p in css_paths:
            if p.exists():
                provider.load_from_file(Gio.File.new_for_path(str(p)))
                break
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._load_css()

    def _load_css(self):
        css_paths = [
            Path(__file__).parent / "style.css",
            Path(__file__).parent.parent / "build" / "resources" / "style.css",
            Path("/app/share/qmic") / "style.css",
        ]
        provider = Gtk.CssProvider()
        for p in css_paths:
            if p.exists():
                provider.load_from_file(Gio.File.new_for_path(str(p)))
                break
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _setup_actions(self):
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", lambda *_: self._show_about())
        self.add_action(about_action)

        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", lambda *_: self._show_shortcuts())
        self.add_action(shortcuts_action)

    def _show_about(self):
        about = Adw.AboutDialog(
            application_name="Ring",
            application_icon="org.qmic.app",
            developer_name="Ring Team",
            version="0.1.0",
            license_type=Gtk.License.GPL_3_0,
            comments="GTK4/Libadwaita frontend for the G'MIC image processing framework",
            website="https://github.com/anomalyco/opencode",
            issue_url="https://github.com/anomalyco/opencode/issues",
        )
        about.present(self._window)

    def _show_shortcuts(self):
        ui_path = _find_ui_file("shortcuts.ui")
        if ui_path:
            builder = Gtk.Builder.new_from_file(ui_path)
        else:
            builder = Gtk.Builder.new_from_resource("/org/qmic/app/shortcuts.ui")
        dialog = None
        for obj in builder.get_objects():
            if isinstance(obj, Adw.ShortcutsDialog):
                dialog = obj
                break
        if dialog:
            dialog.present(self._window)

    def do_activate(self):
        if not self._window:
            self._window = QmicWindow(application=self)
            self._window.connect("close-request", lambda *_: self._cleanup())
        self._window.present()

    def _cleanup(self):
        self._window = None
