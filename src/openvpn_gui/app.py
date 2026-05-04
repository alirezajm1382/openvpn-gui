from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    gi.require_version("Pango", "1.0")
    from gi.repository import Gdk, Gio, GLib, Gtk, Pango
except (ImportError, ValueError) as exc:
    raise SystemExit(
        "OpenVPN GUI requires GTK 3 introspection bindings. "
        "Install python3-gi and gir1.2-gtk-3.0, then try again.\n"
        f"Details: {exc}"
    ) from exc

from . import __app_name__, __version__, paths
from .controller import (
    ControllerError,
    delete_profile_files,
    existing_saved_auth,
    existing_saved_secret,
    openvpn3_available,
    profile_status,
    start_profile,
    stop_profile,
    write_auth_file,
    write_secret_file,
)
from .importer import import_profile
from .network_checks import DEFAULT_TARGETS, PingResult, ping_targets
from .profiles import Profile, ProfileStore


CSS = b"""
.sidebar {
  background: #eef1f5;
  border-right: 1px solid #d4d9e2;
}

.profile-row {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(80, 90, 110, 0.16);
}

.profile-name {
  font-weight: 600;
}

.status-pill {
  border-radius: 999px;
  padding: 6px 12px;
  background: #dde4ee;
  color: #253142;
  font-weight: 600;
}

.status-connected {
  background: #d9f0e4;
  color: #0d5d35;
}

.status-failed {
  background: #f8d7da;
  color: #842029;
}

.main-surface {
  background: #f9fafc;
}

.log-view {
  background: #101820;
  color: #e7edf4;
  font-family: monospace;
  font-size: 10pt;
}

.check-row {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(80, 90, 110, 0.12);
}

.check-pill {
  border-radius: 999px;
  padding: 5px 10px;
  background: #dde4ee;
  color: #253142;
  font-weight: 600;
}

.check-ok {
  background: #d9f0e4;
  color: #0d5d35;
}

.check-failed {
  background: #f8d7da;
  color: #842029;
}
"""


class ProfileRow(Gtk.ListBoxRow):
    def __init__(self, profile: Profile) -> None:
        super().__init__()
        self.profile_id = profile.id
        self.get_style_context().add_class("profile-row")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add(box)

        name = Gtk.Label(label=profile.name, xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.get_style_context().add_class("profile-name")
        box.pack_start(name, False, False, 0)

        source = Gtk.Label(label=Path(profile.config_path).parent.name, xalign=0)
        source.set_ellipsize(Pango.EllipsizeMode.END)
        source.get_style_context().add_class("dim-label")
        box.pack_start(source, False, False, 0)


class CredentialsDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, profile: Profile) -> None:
        super().__init__(
            title=f"Credentials for {profile.name}",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("_Connect", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        content = self.get_content_area()
        content.set_spacing(14)
        content.set_border_width(18)

        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        content.pack_start(grid, True, True, 0)

        self.include_credentials = profile.needs_credentials or existing_saved_auth(profile) is not None
        self.username = Gtk.Entry()
        self.password = Gtk.Entry()
        self.password.set_visibility(False)
        self.password.set_invisible_char("*")

        self.secret = Gtk.Entry()
        self.secret.set_visibility(False)
        self.secret.set_invisible_char("*")
        self.save = Gtk.CheckButton(label="Remember for this profile")

        row = 0
        if self.include_credentials:
            username_label = Gtk.Label(label="Username", xalign=0)
            password_label = Gtk.Label(label="Password", xalign=0)
            grid.attach(username_label, 0, row, 1, 1)
            grid.attach(self.username, 1, row, 1, 1)
            row += 1
            grid.attach(password_label, 0, row, 1, 1)
            grid.attach(self.password, 1, row, 1, 1)
            row += 1

        secret_label = Gtk.Label(label="Secret key", xalign=0)
        grid.attach(secret_label, 0, row, 1, 1)
        grid.attach(self.secret, 1, row, 1, 1)
        row += 1
        grid.attach(self.save, 1, row, 1, 1)

        saved_auth = existing_saved_auth(profile)
        if saved_auth:
            try:
                lines = saved_auth.read_text(encoding="utf-8").splitlines()
                self.username.set_text(lines[0] if lines else "")
                self.password.set_text(lines[1] if len(lines) > 1 else "")
                self.save.set_active(True)
            except OSError:
                pass

        saved_secret = existing_saved_secret(profile)
        if saved_secret:
            try:
                self.secret.set_text(saved_secret.read_text(encoding="utf-8").rstrip("\n"))
                self.save.set_active(True)
            except OSError:
                pass

        self.show_all()

    def values(self) -> tuple[str, str, str, bool]:
        return (
            self.username.get_text(),
            self.password.get_text(),
            self.secret.get_text(),
            self.save.get_active(),
        )


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application)
        self.set_title(__app_name__)
        self.set_default_size(980, 620)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.store = ProfileStore()
        self.selected_profile: Profile | None = None
        self._rows_by_id: dict[str, ProfileRow] = {}
        self._timer_id: int | None = None
        self._check_timer_id: int | None = None
        self._checks_in_flight = False
        self._checks_enabled = False
        self._check_rows: dict[str, dict[str, Gtk.Label]] = {}

        self._install_css()
        self._build_ui()
        self._load_profiles()
        self._select_first_profile()
        self._timer_id = GLib.timeout_add_seconds(2, self.refresh_status)
        self._check_timer_id = GLib.timeout_add_seconds(15, self.run_connectivity_checks_if_connected)

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _build_ui(self) -> None:
        header = Gtk.HeaderBar(title=__app_name__, subtitle=f"OpenVPN profile manager {__version__}")
        header.set_show_close_button(True)
        self.set_titlebar(header)

        self.import_button = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        self.import_button.set_tooltip_text("Import .ovpn profile")
        self.import_button.connect("clicked", self.on_import_clicked)
        header.pack_start(self.import_button)

        self.delete_button = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        self.delete_button.set_tooltip_text("Delete selected profile")
        self.delete_button.connect("clicked", self.on_delete_clicked)
        header.pack_start(self.delete_button)

        self.connect_button = Gtk.Button(label="Connect")
        self.connect_button.connect("clicked", self.on_connect_clicked)
        header.pack_end(self.connect_button)

        root = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self.add(root)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.get_style_context().add_class("sidebar")
        sidebar.set_size_request(290, -1)
        root.pack1(sidebar, resize=False, shrink=False)

        title = Gtk.Label(label="Profiles", xalign=0)
        title.set_margin_top(16)
        title.set_margin_bottom(10)
        title.set_margin_start(16)
        title.set_margin_end(16)
        title.get_style_context().add_class("profile-name")
        sidebar.pack_start(title, False, False, 0)

        self.profile_list = Gtk.ListBox()
        self.profile_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.profile_list.connect("row-selected", self.on_profile_selected)
        sidebar.pack_start(self.profile_list, True, True, 0)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        main.set_border_width(24)
        main.get_style_context().add_class("main-surface")
        root.pack2(main, resize=True, shrink=False)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        main.pack_start(top, False, False, 0)

        self.profile_title = Gtk.Label(label="No profile selected", xalign=0)
        self.profile_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.profile_title.get_style_context().add_class("title-2")
        top.pack_start(self.profile_title, True, True, 0)

        self.status_label = Gtk.Label(label="Disconnected")
        self.status_label.get_style_context().add_class("status-pill")
        top.pack_end(self.status_label, False, False, 0)

        self.detail_label = Gtk.Label(
            label="Import an .ovpn file to get started.",
            xalign=0,
            wrap=True,
        )
        self.detail_label.set_line_wrap(True)
        main.pack_start(self.detail_label, False, False, 0)

        notebook = Gtk.Notebook()
        main.pack_start(notebook, True, True, 0)

        log_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        log_page.set_border_width(0)
        notebook.append_page(log_page, Gtk.Label(label="Log"))

        log_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        log_page.pack_start(log_header, False, False, 0)

        log_title = Gtk.Label(label="Connection Log", xalign=0)
        log_title.get_style_context().add_class("profile-name")
        log_header.pack_start(log_title, True, True, 0)

        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_button.set_tooltip_text("Refresh status")
        self.refresh_button.connect("clicked", lambda *_args: self.refresh_status())
        log_header.pack_end(self.refresh_button, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        log_page.pack_start(scroller, True, True, 0)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_view.get_style_context().add_class("log-view")
        scroller.add(self.log_view)

        checks_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        checks_page.set_border_width(0)
        notebook.append_page(checks_page, Gtk.Label(label="Checks"))

        checks_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        checks_page.pack_start(checks_header, False, False, 0)

        checks_title = Gtk.Label(label="Development URLs", xalign=0)
        checks_title.get_style_context().add_class("profile-name")
        checks_header.pack_start(checks_title, True, True, 0)

        self.check_status_label = Gtk.Label(label="Paused", xalign=1)
        checks_header.pack_start(self.check_status_label, False, False, 0)

        self.check_refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.check_refresh_button.set_tooltip_text("Refresh checks")
        self.check_refresh_button.connect("clicked", self.on_check_refresh_clicked)
        checks_header.pack_end(self.check_refresh_button, False, False, 0)

        check_scroller = Gtk.ScrolledWindow()
        check_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        check_scroller.set_shadow_type(Gtk.ShadowType.IN)
        checks_page.pack_start(check_scroller, True, True, 0)

        self.check_list = Gtk.ListBox()
        self.check_list.set_selection_mode(Gtk.SelectionMode.NONE)
        check_scroller.add(self.check_list)
        for target in DEFAULT_TARGETS:
            self.add_check_row(target)

        self.show_all()

    def add_check_row(self, target: str) -> None:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.get_style_context().add_class("check-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add(box)

        target_label = Gtk.Label(label=target, xalign=0)
        target_label.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(target_label, True, True, 0)

        latency_label = Gtk.Label(label="--", xalign=1)
        latency_label.set_width_chars(10)
        box.pack_start(latency_label, False, False, 0)

        checked_label = Gtk.Label(label="--", xalign=1)
        checked_label.set_width_chars(8)
        box.pack_start(checked_label, False, False, 0)

        state_label = Gtk.Label(label="Paused")
        state_label.set_width_chars(10)
        state_label.get_style_context().add_class("check-pill")
        box.pack_start(state_label, False, False, 0)

        self._check_rows[target] = {
            "state": state_label,
            "latency": latency_label,
            "checked": checked_label,
        }
        self.check_list.add(row)

    def _load_profiles(self) -> None:
        for child in self.profile_list.get_children():
            self.profile_list.remove(child)
        self._rows_by_id.clear()

        for profile in self.store.profiles:
            row = ProfileRow(profile)
            self.profile_list.add(row)
            self._rows_by_id[profile.id] = row

        self.profile_list.show_all()

    def _select_first_profile(self) -> None:
        rows = self.profile_list.get_children()
        if rows:
            self.profile_list.select_row(rows[0])
        else:
            self.selected_profile = None
            self.update_profile_view(None)

    def on_profile_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            self.selected_profile = None
        else:
            self.selected_profile = self.store.get(row.profile_id)  # type: ignore[attr-defined]
        self.update_profile_view(self.selected_profile)

    def update_profile_view(self, profile: Profile | None) -> None:
        self.delete_button.set_sensitive(profile is not None)
        self.connect_button.set_sensitive(profile is not None)

        if profile is None:
            self.profile_title.set_text("No profile selected")
            self.detail_label.set_text("Import an .ovpn file to get started.")
            self.connect_button.set_label("Connect")
            self.set_status("Disconnected", running=False)
            self.log_view.get_buffer().set_text("")
            self.set_connectivity_paused()
            return

        self.profile_title.set_text(profile.name)
        self.detail_label.set_text(str(profile.path))
        self.refresh_status()

    def set_status(self, label: str, running: bool) -> None:
        context = self.status_label.get_style_context()
        context.remove_class("status-connected")
        context.remove_class("status-failed")
        if running and label == "Connected":
            context.add_class("status-connected")
        elif "failed" in label.lower() or "error" in label.lower():
            context.add_class("status-failed")
        self.status_label.set_text(label)
        self.connect_button.set_label("Disconnect" if running else "Connect")

    def refresh_status(self) -> bool:
        profile = self.selected_profile
        if not profile:
            return True

        status = profile_status(profile)
        self.set_status(status.state, status.running)
        self.log_view.get_buffer().set_text(status.log_tail or "No log output yet.")
        self.update_connectivity_state(status.running and status.state == "Connected")
        return True

    def update_connectivity_state(self, enabled: bool) -> None:
        if self._checks_enabled == enabled:
            return
        self._checks_enabled = enabled
        if enabled:
            self.check_status_label.set_text("Checking")
            self.start_connectivity_checks()
        else:
            self.set_connectivity_paused()

    def set_connectivity_paused(self) -> None:
        self._checks_enabled = False
        self.check_status_label.set_text("Paused")
        for target in DEFAULT_TARGETS:
            self.update_check_row(target, "Paused", "--", "--", ok=None, message="VPN disconnected")

    def run_connectivity_checks_if_connected(self) -> bool:
        if self._checks_enabled:
            self.start_connectivity_checks()
        return True

    def on_check_refresh_clicked(self, _button: Gtk.Button) -> None:
        if not self._checks_enabled:
            self.check_status_label.set_text("Paused")
            return
        self.start_connectivity_checks()

    def start_connectivity_checks(self) -> None:
        profile = self.selected_profile
        if not profile or not self._checks_enabled:
            return
        if self._checks_in_flight:
            return

        self._checks_in_flight = True
        self.check_status_label.set_text("Checking")
        profile_id = profile.id

        thread = threading.Thread(
            target=self.run_connectivity_checks_worker,
            args=(profile_id,),
            daemon=True,
        )
        thread.start()

    def run_connectivity_checks_worker(self, profile_id: str) -> None:
        results = ping_targets()
        GLib.idle_add(self.apply_connectivity_results, profile_id, results)

    def apply_connectivity_results(self, profile_id: str, results: list[PingResult]) -> bool:
        self._checks_in_flight = False
        profile = self.selected_profile
        if not profile or profile.id != profile_id or not self._checks_enabled:
            return False

        ok_count = 0
        for result in results:
            if result.ok:
                ok_count += 1
            latency = f"{result.latency_ms:.1f} ms" if result.latency_ms is not None else "--"
            checked = result.checked_at.strftime("%H:%M:%S")
            state = "Online" if result.ok else "Failed"
            self.update_check_row(result.target, state, latency, checked, ok=result.ok, message=result.message)

        self.check_status_label.set_text(f"{ok_count}/{len(results)} online")
        return False

    def update_check_row(
        self,
        target: str,
        state: str,
        latency: str,
        checked: str,
        ok: bool | None,
        message: str,
    ) -> None:
        row = self._check_rows.get(target)
        if not row:
            return

        state_label = row["state"]
        state_label.set_text(state)
        state_label.set_tooltip_text(message)
        state_context = state_label.get_style_context()
        state_context.remove_class("check-ok")
        state_context.remove_class("check-failed")
        if ok is True:
            state_context.add_class("check-ok")
        elif ok is False:
            state_context.add_class("check-failed")

        row["latency"].set_text(latency)
        row["checked"].set_text(checked)

    def on_import_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Import OpenVPN profile",
            self,
            Gtk.FileChooserAction.OPEN,
            "_Import",
            "_Cancel",
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name("OpenVPN profiles")
        file_filter.add_pattern("*.ovpn")
        dialog.add_filter(file_filter)

        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()

        if response != Gtk.ResponseType.ACCEPT or not filename:
            return

        try:
            profile = import_profile(Path(filename))
            self.store.add(profile)
        except Exception as exc:
            self.show_error("Import failed", str(exc))
            return

        self._load_profiles()
        row = self._rows_by_id.get(profile.id)
        if row:
            self.profile_list.select_row(row)

    def on_connect_clicked(self, _button: Gtk.Button) -> None:
        profile = self.selected_profile
        if not profile:
            return

        status = profile_status(profile)
        if status.running:
            self.stop_selected(profile)
        else:
            self.start_selected(profile)

    def start_selected(self, profile: Profile) -> None:
        if not openvpn3_available() and not shutil.which("pkexec"):
            self.show_error("pkexec is missing", "Install pkexec and polkitd, then start the app again.")
            return

        auth_path = existing_saved_auth(profile)
        secret_path = existing_saved_secret(profile)
        needs_prompt = (profile.needs_credentials and not auth_path) or (profile.needs_secret and not secret_path)

        if needs_prompt:
            dialog = CredentialsDialog(self, profile)
            response = dialog.run()
            username, password, secret, save = dialog.values()
            dialog.destroy()

            if response != Gtk.ResponseType.OK:
                return
            if profile.needs_credentials and (not username or not password):
                self.show_error("Credentials required", "Enter both username and password.")
                return
            if profile.needs_secret and not secret:
                self.show_error("Secret key required", "Enter the secret key for this profile.")
                return
            if profile.needs_credentials:
                auth_path = write_auth_file(profile, username, password, save)
            if secret:
                secret_path = write_secret_file(profile, secret, save)

        try:
            start_profile(profile, auth_path, secret_path)
        except ControllerError as exc:
            self.show_error("Could not connect", str(exc))
        finally:
            self.refresh_status()

    def stop_selected(self, profile: Profile) -> None:
        try:
            stop_profile(profile)
        except ControllerError as exc:
            self.show_error("Could not disconnect", str(exc))
        finally:
            self.refresh_status()

    def on_delete_clicked(self, _button: Gtk.Button) -> None:
        profile = self.selected_profile
        if not profile:
            return

        status = profile_status(profile)
        if status.running:
            self.show_error("Profile is connected", "Disconnect before deleting this profile.")
            return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text=f"Delete {profile.name}?",
        )
        dialog.add_button("_Delete", Gtk.ResponseType.OK)
        dialog.format_secondary_text("The imported config and copied certificate files will be removed.")
        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        try:
            delete_profile_files(profile)
            self.store.remove(profile.id)
        except Exception as exc:
            self.show_error("Delete failed", str(exc))
            return

        self._load_profiles()
        self._select_first_profile()

    def show_error(self, title: str, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


class OpenVpnGuiApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="com.openvpngui.Client",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.window: MainWindow | None = None

    def do_activate(self) -> None:
        if not self.window:
            self.window = MainWindow(self)
        self.window.present()


def main(argv: list[str] | None = None) -> int:
    app = OpenVpnGuiApplication()
    return app.run(sys.argv if argv is None else argv)
