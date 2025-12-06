import sys
import gi
import json
import subprocess
import threading
import os

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, Gdk, GLib

class GentooInstallerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.gentoo.installer",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.pages = ["welcome", "disk_setup", "config", "install", "finish"]
        self.window = None
        self.partitions = {}

    def do_activate(self):
        if not self.window:
            self.window = Gtk.ApplicationWindow(application=self,
                                                 title="Gentoo Installer")
            self.window.set_default_size(800, 600)

            # Main layout
            main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            self.window.set_child(main_box)

            # Header Bar
            header = Gtk.HeaderBar()
            header.set_show_title_buttons(True)
            self.window.set_titlebar(header)


            # Wizard pages
            self.stack = Gtk.Stack()
            self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
            self.stack.set_vexpand(True)
            main_box.append(self.stack)

            # Welcome Page
            welcome_label = Gtk.Label(label="Welcome to the Gentoo Installer!")
            self.stack.add_named(welcome_label, "welcome")

            # Disk Setup Page
            disk_setup_page = self._build_disk_setup_page()
            self.stack.add_named(disk_setup_page, "disk_setup")
            
            # Config page
            config_page = self._build_config_page()
            self.stack.add_named(config_page, "config")

            # Install page
            install_page = self._build_install_page()
            self.stack.add_named(install_page, "install")

            # Finish page
            finish_page = Gtk.Label(label="Installation Finished! You can now reboot.")
            self.stack.add_named(finish_page, "finish")

            # Navigation
            nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            nav_box.set_halign(Gtk.Align.CENTER)
            main_box.append(nav_box)

            self.back_button = Gtk.Button(label="Back")
            self.back_button.connect("clicked", self.on_back_clicked)
            self.back_button.set_sensitive(False)
            nav_box.append(self.back_button)

            self.next_button = Gtk.Button(label="Next")
            self.next_button.connect("clicked", self.on_next_clicked)
            nav_box.append(self.next_button)

        self.window.present()
        self._refresh_disk_list() # Initial scan

    def _build_config_page(self):
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        page_box.append(grid)

        grid.attach(Gtk.Label(label="Hostname:"), 0, 0, 1, 1)
        self.hostname_entry = Gtk.Entry(text="gentoo")
        grid.attach(self.hostname_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Username:"), 0, 1, 1, 1)
        self.username_entry = Gtk.Entry(text="user")
        grid.attach(self.username_entry, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Password:"), 0, 2, 1, 1)
        self.password_entry = Gtk.Entry(visibility=False)
        grid.attach(self.password_entry, 1, 2, 1, 1)
        
        return page_box

    def _build_install_page(self):
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_vexpand(True)
        scrolled_window.set_has_frame(True)
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.log_view = Gtk.TextView(editable=False, cursor_visible=False)
        self.log_buffer = self.log_view.get_buffer()
        scrolled_window.set_child(self.log_view)
        page_box.append(scrolled_window)

        self.progress_bar = Gtk.ProgressBar()
        page_box.append(self.progress_bar)

        return page_box

    def _build_disk_setup_page(self):
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Scrolled window for the tree view
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_has_frame(True)
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)
        page_box.append(scrolled_window)

        # TreeView for disks and partitions
        self.disk_store = Gtk.TreeStore(str, str, str, str, str) # name, size, type, fstype, path
        self.disk_view = Gtk.TreeView(model=self.disk_store)
        scrolled_window.set_child(self.disk_view)

        for i, title in enumerate(["Device", "Size", "Type", "Filesystem"]):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=i)
            self.disk_view.append_column(column)

        # Partition selection UI
        selection_grid = Gtk.Grid(column_spacing=10, row_spacing=10, margin_top=10)
        self.root_part_combo = Gtk.ComboBoxText()
        self.boot_part_combo = Gtk.ComboBoxText()
        
        selection_grid.attach(Gtk.Label(label="Root Partition (/):"), 0, 0, 1, 1)
        selection_grid.attach(self.root_part_combo, 1, 0, 1, 1)
        selection_grid.attach(Gtk.Label(label="Boot Partition (/boot, optional):"), 0, 1, 1, 1)
        selection_grid.attach(self.boot_part_combo, 1, 1, 1, 1)
        
        # Refresh button
        refresh_button = Gtk.Button(label="Refresh Disks")
        refresh_button.connect("clicked", lambda x: self._refresh_disk_list())
        
        self.format_partitions_check = Gtk.CheckButton(label="Format selected partitions (ext4)")
        
        page_box.append(selection_grid)
        page_box.append(self.format_partitions_check)
        page_box.append(refresh_button)

        return page_box
    
    def _refresh_disk_list(self):
        self.disk_store.clear()
        self.root_part_combo.remove_all()
        self.boot_part_combo.remove_all()
        self.partitions = {}

        try:
            lsblk_output = subprocess.check_output(
                ["lsblk", "-Jb", "-o", "NAME,SIZE,TYPE,FSTYPE,PATH"], text=True
            )
            devices = json.loads(lsblk_output)["blockdevices"]

            self.boot_part_combo.append_text("None")

            for device in devices:
                if device["type"] == "disk":
                    piter = self.disk_store.append(None, [device["name"], f"{int(device['size']) / 1024**3:.2f} GB", device["type"], "", device["path"]])
                    if "children" in device:
                        for part in device["children"]:
                            if part["type"] == "part":
                                self.disk_store.append(piter, [part["name"], f"{int(part['size']) / 1024**3:.2f} GB", part["type"], part["fstype"], part["path"]])
                                self.partitions[part['path']] = part
                                self.root_part_combo.append_text(part["path"])
                                self.boot_part_combo.append_text(part["path"])
            
            self.root_part_combo.set_active(0)
            self.boot_part_combo.set_active(0)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
            self._show_error_dialog(f"Error reading disk information: {e}")

    def start_installation(self):
        root_part = self.root_part_combo.get_active_text()
        boot_part = self.boot_part_combo.get_active_text()
        hostname = self.hostname_entry.get_text()
        username = self.username_entry.get_text()
        password = self.password_entry.get_text()

        if not root_part or root_part == "None":
            self._show_error_dialog("A root partition must be selected.")
            self.stack.set_visible_child_name("disk_setup")
            return

        summary = f"""
<b>Installation Summary:</b>
- <b>Root Partition:</b> {root_part}
- <b>Boot Partition:</b> {boot_part}
- <b>Format Partitions:</b> {'Yes' if self.format_partitions_check.get_active() else 'No'}
- <b>Hostname:</b> {hostname}
- <b>New User:</b> {username}

<b>Warning:</b> This will modify the selected partitions. If formatting is enabled, all data on them will be destroyed. Proceed?
"""
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Confirm Installation Details",
        )
        dialog.format_secondary_markup(summary)
        dialog.connect("response", self._on_confirm_response)
        dialog.show()

    def _on_confirm_response(self, dialog, response_id):
        dialog.destroy()
        if response_id == Gtk.ResponseType.OK:
            self.back_button.set_sensitive(False)
            self.next_button.set_sensitive(False)
            install_thread = threading.Thread(target=self._run_installation_thread)
            install_thread.daemon = True
            install_thread.start()
        else:
            self.stack.set_visible_child_name("config")
            self.back_button.set_sensitive(True)
            self.next_button.set_sensitive(True)

    def _run_installation_thread(self):
        try:
            GLib.idle_add(self.progress_bar.set_fraction, 0.0)
            GLib.idle_add(self._update_log, "Starting installation...\n")

            root_part = self.root_part_combo.get_active_text()
            boot_part = self.boot_part_combo.get_active_text()
            format_parts = self.format_partitions_check.get_active()
            hostname = self.hostname_entry.get_text()
            username = self.username_entry.get_text()
            password = self.password_entry.get_text()
            mount_point = "/mnt/gentoo"

            # --- 1. Formatting ---
            GLib.idle_add(self.progress_bar.set_fraction, 0.1)
            if format_parts:
                GLib.idle_add(self._update_log, f"Formatting {root_part} as ext4...\n")
                if not self._run_command(["mkfs.ext4", "-F", root_part]): return
                if boot_part != "None":
                    GLib.idle_add(self._update_log, f"Formatting {boot_part} as ext4...\n")
                    if not self._run_command(["mkfs.ext4", "-F", boot_part]): return
            
            # --- 2. Mounting ---
            GLib.idle_add(self.progress_bar.set_fraction, 0.2)
            GLib.idle_add(self._update_log, f"Mounting {root_part} to {mount_point}...\n")
            if not self._run_command(["mkdir", "-p", mount_point]): return
            if not self._run_command(["mount", root_part, mount_point]): return
            
            if boot_part != "None":
                GLib.idle_add(self._update_log, f"Mounting {boot_part} to {mount_point}/boot...\n")
                if not self._run_command(["mkdir", "-p", f"{mount_point}/boot"]): return
                if not self._run_command(["mount", boot_part, f"{mount_point}/boot"]): return

            # --- 3. Rsync ---
            GLib.idle_add(self.progress_bar.set_fraction, 0.3)
            GLib.idle_add(self._update_log, "Cloning the live system with rsync (this will take a while)...\n")
            rsync_cmd = [
                "rsync", "-aAXv", "--exclude", 
                str({"--exclude": item for item in [
                    "/dev/*", "/proc/*", "/sys/*", "/tmp/*", "/run/*", 
                    "/mnt/*", "/media/*", "/lost+found"
                ]}),
                "/", mount_point
            ]
            # A bit of a hack to get rsync --exclude working with spaces
            rsync_cmd = "rsync -aAXv --exclude=/dev/* --exclude=/proc/* --exclude=/sys/* --exclude=/tmp/* --exclude=/run/* --exclude=/mnt/* --exclude=/media/* --exclude=/lost+found / {}".format(mount_point).split()
            if not self._run_command(rsync_cmd): return

            # --- 4. Chroot Configuration ---
            GLib.idle_add(self.progress_bar.set_fraction, 0.8)
            GLib.idle_add(self._update_log, "Configuring the new system...\n")
            
            root_uuid = self._get_uuid(root_part)
            boot_uuid = self._get_uuid(boot_part) if boot_part != "None" else None

            fstab_content = f"UUID={root_uuid}\t/\text4\tdefaults,noatime\t0 1\n"
            if boot_uuid:
                fstab_content += f"UUID={boot_uuid}\t/boot\text4\tdefaults,noatime\t0 2\n"

            chroot_script_path = f"{mount_point}/tmp/configure.sh"
            chroot_script_content = f"""#!/bin/bash
mount -t proc /proc /proc
mount --rbind /sys /sys
mount --rbind /dev /dev
echo '{hostname}' > /etc/hostname
echo "{fstab_content}" > /etc/fstab
useradd -m -G users,wheel,audio -s /bin/bash {username}
echo '{username}:{password}' | chpasswd
emerge-webrsync
emerge --sync
emerge --oneshot sys-kernel/gentoo-sources sys-kernel/genkernel
genkernel all
grub-install {root_part.rsplit('/',1)[0]}
grub-mkconfig -o /boot/grub/grub.cfg
exit
"""
            with open(chroot_script_path, "w") as f:
                f.write(chroot_script_content)
            
            if not self._run_command(["chmod", "+x", chroot_script_path]): return
            if not self._run_command(["chroot", mount_point, "/tmp/configure.sh"]): return

            # --- 5. Unmount ---
            GLib.idle_add(self.progress_bar.set_fraction, 0.95)
            GLib.idle_add(self._update_log, "Unmounting filesystems...\n")
            if boot_part != "None":
                self._run_command(["umount", "-l", f"{mount_point}/boot"])
            self._run_command(["umount", "-l", mount_point])

            GLib.idle_add(self.progress_bar.set_fraction, 1.0)
            GLib.idle_add(self._update_log, "Installation complete!\n")
            GLib.idle_add(self._on_installation_finished)

        except Exception as e:
            GLib.idle_add(self._show_error_dialog, f"An unexpected error occurred: {e}")

    def _get_uuid(self, partition_path):
        """Helper to get UUID for a partition."""
        if not partition_path or partition_path == "None":
            return None
        try:
            return subprocess.check_output(
                ["lsblk", "-no", "UUID", partition_path], text=True
            ).strip()
        except subprocess.CalledProcessError:
            return None

    def _on_installation_finished(self):
        self.stack.set_visible_child_name("finish")
        self.next_button.set_label("Reboot")
        self.next_button.set_sensitive(True)
        self.next_button.disconnect_by_func(self.on_next_clicked)
        self.next_button.connect("clicked", lambda x: self._run_command(["reboot"]))


    def _update_log(self, message):
        self.log_buffer.insert_at_cursor(message)
        # Autoscroll
        adj = self.log_view.get_parent().get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False # So GLib.idle_add doesn't call it again
    
    def _run_command(self, command, log=True):
        if log:
            GLib.idle_add(self._update_log, f"Running command: {' '.join(command)}\n")
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        for line in iter(process.stdout.readline, ''):
            if log:
                GLib.idle_add(self._update_log, line)
        
        process.wait()
        
        if process.returncode != 0:
            error_message = f"Command failed with exit code {process.returncode}: {' '.join(command)}"
            GLib.idle_add(self._show_error_dialog, error_message)
            return False
        return True


    def _show_error_dialog(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.show()

    def on_back_clicked(self, button):
        current_name = self.stack.get_visible_child_name()
        current_index = self.pages.index(current_name)
        
        if current_index > 0:
            new_index = current_index - 1
            self.stack.set_visible_child_name(self.pages[new_index])
            
            self.back_button.set_sensitive(new_index > 0)
            self.next_button.set_label("Next")
            self.next_button.set_sensitive(True)


    def on_next_clicked(self, button):
        current_name = self.stack.get_visible_child_name()
        
        if current_name == "finish":
            # This is handled by the reboot button now
            return

        current_index = self.pages.index(current_name)

        if current_index < len(self.pages) - 1:
            new_index = current_index + 1
            
            if self.pages[new_index] == "install":
                # Move to install page and *then* start the process
                self.stack.set_visible_child_name("install")
                self.start_installation()
            else:
                self.stack.set_visible_child_name(self.pages[new_index])

            self.back_button.set_sensitive(new_index > 0)

            if self.pages[new_index] == "finish":
                self.next_button.set_label("Finish")
            elif self.pages[new_index] == "install":
                self.back_button.set_sensitive(False)
                self.next_button.set_sensitive(False)
            
def main():
    app = GentooInstallerApp()
    sys.exit(app.run(sys.argv))

if __name__ == "__main__":
    main()
