#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import queue
import threading
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import ffw_save_transfer as core
from PIL import Image, ImageDraw


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_BG = "#0b1020"
PANEL = "#111827"
PANEL_2 = "#172033"
CARD = "#1f2a44"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
ACCENT = "#3b82f6"
GREEN = "#22c55e"
RED = "#ef4444"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Far Far West Save Studio")
        self.geometry("1180x760")
        self.minsize(1040, 680)
        self.configure(fg_color=APP_BG)

        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.accounts: list[core.SteamAccount] = []
        self.profiles: dict[str, core.SteamAccount] = {}
        self.avatars: dict[str, ctk.CTkImage] = {}

        self.plaintext: bytes | None = None
        self.crypto_profile = ""
        self.loaded_steam_id = ""
        self.inventory_entries: list[core.InventoryEntry] = []
        self.inventory_inputs: dict[int, ctk.CTkEntry] = {}
        self.inventory_values: dict[int, int] = {}

        self.source_save = ctk.StringVar()
        self.source_steamid = ctk.StringVar()
        self.target_steamid = ctk.StringVar()
        self.output_path = ctk.StringVar()
        self.party_suffix = ctk.StringVar(value=core.DEFAULT_PARTY_SUFFIX)
        self.rewrite_payload = ctk.BooleanVar(value=True)
        self.copy_backup = ctk.BooleanVar(value=True)
        self.profile_input = ctk.StringVar()
        self.editor_search = ctk.StringVar()
        self.editor_category = ctk.StringVar(value="All")

        self._build_shell()
        self._build_transfer()
        self._build_accounts()
        self._build_editor()
        self._build_log()
        self.refresh_accounts()
        self.after(150, self._poll)

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color="#080d1a")
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(side, text="Far Far West", font=("Segoe UI", 24, "bold"), text_color=TEXT).grid(row=0, column=0, sticky="w", padx=24, pady=(28, 0))
        ctk.CTkLabel(side, text="Save Studio", font=("Segoe UI", 18), text_color=MUTED).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 28))

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for i, name in enumerate(("Transfer", "Accounts", "Editor", "Activity"), start=2):
            self.nav_buttons[name] = ctk.CTkButton(
                side,
                text=name,
                height=44,
                corner_radius=12,
                anchor="w",
                fg_color="transparent",
                hover_color=PANEL_2,
                command=lambda n=name: self.show_page(n),
            )
            self.nav_buttons[name].grid(row=i, column=0, sticky="ew", padx=16, pady=4)

        ctk.CTkLabel(side, text="Unofficial save tool\nBack up important saves.", justify="left", text_color=MUTED).grid(row=8, column=0, sticky="sw", padx=24, pady=24)

        self.content = ctk.CTkFrame(self, fg_color=APP_BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.content, fg_color=APP_BG)
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(24, 10))
        header.grid_columnconfigure(0, weight=1)
        self.page_title = ctk.CTkLabel(header, text="Transfer", font=("Segoe UI", 30, "bold"), text_color=TEXT)
        self.page_title.grid(row=0, column=0, sticky="w")
        self.status = ctk.CTkLabel(header, text="Ready", text_color=MUTED)
        self.status.grid(row=0, column=1, sticky="e")

        self.pages = ctk.CTkFrame(self.content, fg_color=APP_BG, corner_radius=0)
        self.pages.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 30))
        self.pages.grid_columnconfigure(0, weight=1)
        self.pages.grid_rowconfigure(0, weight=1)
        self.page_frames: dict[str, ctk.CTkFrame] = {}
        for name in ("Transfer", "Accounts", "Editor", "Activity"):
            frame = ctk.CTkFrame(self.pages, fg_color=APP_BG, corner_radius=0)
            frame.grid(row=0, column=0, sticky="nsew")
            self.page_frames[name] = frame
        self.show_page("Transfer")

    def show_page(self, name: str) -> None:
        self.page_frames[name].tkraise()
        self.page_title.configure(text=name if name != "Editor" else "Save Editor")
        for key, button in self.nav_buttons.items():
            button.configure(fg_color=ACCENT if key == name else "transparent")

    def card(self, parent: ctk.CTkFrame, **grid: object) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=18, border_width=1, border_color="#243047")
        frame.grid(**grid)
        return frame

    def field(self, parent: ctk.CTkFrame, row: int, label: str, var: ctk.StringVar, button: str | None = None, command: object | None = None) -> None:
        ctk.CTkLabel(parent, text=label, text_color=MUTED, font=("Segoe UI", 13, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", padx=18, pady=(14, 5))
        entry = ctk.CTkEntry(parent, textvariable=var, height=42, corner_radius=12, fg_color="#0c1324", border_color="#26324a")
        entry.grid(row=row + 1, column=0, sticky="ew", padx=(18, 8), pady=(0, 4))
        if button:
            ctk.CTkButton(parent, text=button, height=42, corner_radius=12, command=command).grid(row=row + 1, column=1, sticky="ew", padx=(0, 18), pady=(0, 4))

    def _build_transfer(self) -> None:
        page = self.page_frames["Transfer"]
        page.grid_columnconfigure(0, weight=2)
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(0, weight=1)

        left = self.card(page, row=0, column=0, sticky="nsew", padx=(0, 18))
        left.grid_columnconfigure(0, weight=1)
        left.grid_columnconfigure(1, minsize=150)
        ctk.CTkLabel(left, text="Move a save to another Steam account", font=("Segoe UI", 20, "bold"), text_color=TEXT).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(left, text="Choose the old save, pick a target SteamID, and generate a new encrypted save.", text_color=MUTED).grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 10))
        self.field(left, 2, "Old save file", self.source_save, "Browse", self.browse_source)
        self.field(left, 4, "Source SteamID64", self.source_steamid, "From filename", self.source_from_filename)
        self.field(left, 6, "Target SteamID64", self.target_steamid)
        self.field(left, 8, "Output save file", self.output_path, "Save as", self.browse_output)
        self.field(left, 10, "Party suffix", self.party_suffix)
        ctk.CTkCheckBox(left, text="Replace old SteamID text inside decrypted payload", variable=self.rewrite_payload).grid(row=12, column=0, columnspan=2, sticky="w", padx=18, pady=(16, 6))
        ctk.CTkCheckBox(left, text="Create backup if output already exists", variable=self.copy_backup).grid(row=13, column=0, columnspan=2, sticky="w", padx=18, pady=6)
        ctk.CTkButton(left, text="Transfer Save", height=52, corner_radius=14, fg_color=GREEN, hover_color="#16a34a", command=self.transfer).grid(row=14, column=0, columnspan=2, sticky="ew", padx=18, pady=20)

        right = self.card(page, row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(right, text="Target account", font=("Segoe UI", 20, "bold"), text_color=TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 8))
        self.selected_avatar = ctk.CTkLabel(right, text="")
        self.selected_avatar.grid(row=1, column=0, sticky="w", padx=18, pady=(8, 4))
        self.selected_name = ctk.CTkLabel(right, text="No account selected", font=("Segoe UI", 15, "bold"), justify="left", text_color=TEXT)
        self.selected_name.grid(row=2, column=0, sticky="w", padx=18)
        self.selected_id = ctk.CTkLabel(right, text="Pick one in Accounts", text_color=MUTED)
        self.selected_id.grid(row=3, column=0, sticky="w", padx=18, pady=(0, 14))
        ctk.CTkEntry(right, textvariable=self.profile_input, height=42, placeholder_text="Steam URL, vanity, or SteamID64").grid(row=4, column=0, sticky="ew", padx=18, pady=(18, 8))
        ctk.CTkButton(right, text="Resolve Profile", height=42, corner_radius=12, command=self.resolve_profile).grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 8))
        ctk.CTkButton(right, text="Open Accounts", height=42, corner_radius=12, fg_color=CARD, hover_color="#334155", command=lambda: self.show_page("Accounts")).grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 18))

    def _build_accounts(self) -> None:
        page = self.page_frames["Accounts"]
        page.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(page, fg_color=APP_BG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Steam accounts found on this PC", text_color=MUTED).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(top, text="Refresh", width=140, command=self.refresh_accounts).grid(row=0, column=1, sticky="e")
        self.accounts_scroll = ctk.CTkScrollableFrame(page, fg_color=APP_BG, corner_radius=0)
        self.accounts_scroll.grid(row=1, column=0, sticky="nsew")
        page.grid_rowconfigure(1, weight=1)

    def _build_editor(self) -> None:
        page = self.page_frames["Editor"]
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        top = self.card(page, row=0, column=0, sticky="ew", pady=(0, 16))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Runtime inventory editor", font=("Segoe UI", 20, "bold"), text_color=TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(top, text="Loads editable integer amounts from the decrypted runtimeInventory block. A backup is created before saving over an existing file.", text_color=MUTED).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 16))
        ctk.CTkButton(top, text="Load Current Save", height=42, command=self.load_editor_save).grid(row=0, column=1, rowspan=2, padx=18)

        controls = ctk.CTkFrame(page, fg_color=APP_BG)
        controls.grid(row=1, column=0, sticky="nsew")
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_rowconfigure(2, weight=1)
        bar = ctk.CTkFrame(controls, fg_color=APP_BG)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(bar, textvariable=self.editor_search, placeholder_text="Search inventory, jokers, skins, quests...", height=40).grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.editor_search.trace_add("write", lambda *_: self.render_inventory())
        self.category_menu = ctk.CTkOptionMenu(bar, variable=self.editor_category, values=["All"], command=lambda _v: self.render_inventory(), width=180)
        self.category_menu.grid(row=0, column=1)
        self.editor_summary = ctk.CTkLabel(controls, text="Load a save to edit values.", text_color=MUTED)
        self.editor_summary.grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.inventory_scroll = ctk.CTkScrollableFrame(controls, fg_color=APP_BG, corner_radius=0)
        self.inventory_scroll.grid(row=2, column=0, sticky="nsew")
        bottom = ctk.CTkFrame(controls, fg_color=APP_BG)
        bottom.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        bottom.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(bottom, text="Save Edited Copy", height=46, fg_color=GREEN, hover_color="#16a34a", command=self.save_editor_copy).grid(row=0, column=1, padx=(10, 0))

    def _build_log(self) -> None:
        page = self.page_frames["Activity"]
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self.log = ctk.CTkTextbox(page, fg_color=PANEL, corner_radius=18, border_width=1, border_color="#243047", font=("Cascadia Mono", 12))
        self.log.grid(row=0, column=0, sticky="nsew")

    def browse_source(self) -> None:
        initial = str(core.SAVE_DIR) if core.SAVE_DIR.exists() else str(Path.home())
        path = filedialog.askopenfilename(title="Choose Far Far West save", initialdir=initial, filetypes=[("Far Far West saves", "*.save"), ("All files", "*.*")])
        if path:
            self.source_save.set(path)
            self.source_from_filename(silent=True)
            self.set_default_output()

    def browse_output(self) -> None:
        target = self.target_steamid.get().strip() or self.source_steamid.get().strip() or "edited"
        path = filedialog.asksaveasfilename(title="Choose output save", initialfile=f"{target}.save", defaultextension=".save", filetypes=[("Far Far West saves", "*.save"), ("All files", "*.*")])
        if path:
            self.output_path.set(path)

    def source_from_filename(self, silent: bool = False) -> None:
        try:
            self.source_steamid.set(core.infer_steam_id(Path(self.source_save.get().strip())))
            if not silent:
                self.write_log(f"Source SteamID found: {self.source_steamid.get()}")
        except Exception as exc:
            if not silent:
                messagebox.showerror("Source SteamID", str(exc))

    def set_default_output(self) -> None:
        source = self.source_save.get().strip()
        target = self.target_steamid.get().strip()
        if source and target:
            self.output_path.set(str(Path(source).with_name(f"{target}.save")))

    def refresh_accounts(self) -> None:
        self.accounts = core.discover_steam_accounts()
        self.render_accounts()
        self.write_log(f"Found {len(self.accounts)} local SteamID candidate(s).")
        for account in self.accounts:
            threading.Thread(target=self._profile_worker, args=(account.steam_id,), daemon=True).start()

    def render_accounts(self) -> None:
        for child in self.accounts_scroll.winfo_children():
            child.destroy()
        if not self.accounts:
            ctk.CTkLabel(self.accounts_scroll, text="No local accounts found. Paste a Steam profile on Transfer.", text_color=MUTED).pack(anchor="w", pady=20)
            return
        for account in self.accounts:
            profile = self.profiles.get(account.steam_id, account)
            card = ctk.CTkFrame(self.accounts_scroll, fg_color=PANEL, corner_radius=18, border_width=1, border_color="#243047")
            card.pack(fill="x", pady=8, padx=4)
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(card, text="", image=self.avatar_for(profile)).grid(row=0, column=0, rowspan=2, padx=16, pady=14)
            ctk.CTkLabel(card, text=profile.persona_name or account.label.split(" - ")[0], font=("Segoe UI", 16, "bold"), text_color=TEXT).grid(row=0, column=1, sticky="sw", pady=(14, 0))
            ctk.CTkLabel(card, text=f"{account.steam_id}   •   {account.source}", text_color=MUTED).grid(row=1, column=1, sticky="nw", pady=(0, 14))
            ctk.CTkButton(card, text="Use", width=100, command=lambda a=account: self.use_account(a)).grid(row=0, column=2, rowspan=2, padx=16)
        self.update_selected_account()

    def avatar_for(self, account: core.SteamAccount) -> ctk.CTkImage:
        if account.steam_id in self.avatars:
            return self.avatars[account.steam_id]
        image: Image.Image | None = None
        if account.avatar_url:
            try:
                with urllib.request.urlopen(account.avatar_url, timeout=8) as response:
                    image = Image.open(io.BytesIO(response.read())).convert("RGBA").resize((64, 64))
            except Exception:
                image = None
        if image is None:
            image = Image.new("RGBA", (64, 64), "#164e63")
            draw = ImageDraw.Draw(image)
            draw.ellipse((0, 0, 63, 63), fill="#1d4ed8")
            letter = (account.persona_name or account.label or "?")[:1].upper()
            draw.text((32, 32), letter, fill="white", anchor="mm")
        ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(64, 64))
        self.avatars[account.steam_id] = ctk_image
        return ctk_image

    def use_account(self, account: core.SteamAccount) -> None:
        self.target_steamid.set(account.steam_id)
        self.set_default_output()
        self.update_selected_account()
        self.show_page("Transfer")

    def update_selected_account(self) -> None:
        steam_id = self.target_steamid.get().strip()
        account = self.profiles.get(steam_id) or next((a for a in self.accounts if a.steam_id == steam_id), None)
        if account:
            self.selected_avatar.configure(image=self.avatar_for(account))
            self.selected_name.configure(text=account.persona_name or account.label.split(" - ")[0])
            self.selected_id.configure(text=account.steam_id)
        else:
            empty = core.SteamAccount("placeholder", "No account selected", "", "?", "")
            self.selected_avatar.configure(image=self.avatar_for(empty))
            self.selected_name.configure(text="No account selected")
            self.selected_id.configure(text="Pick one in Accounts")

    def _profile_worker(self, steam_id: str) -> None:
        try:
            self.queue.put(("profile", core.fetch_steam_profile(steam_id)))
        except Exception:
            pass

    def resolve_profile(self) -> None:
        value = self.profile_input.get().strip()
        if not value:
            messagebox.showerror("Resolve Profile", "Paste a Steam URL, vanity name, or SteamID64.")
            return
        self.status.configure(text="Resolving profile...")
        threading.Thread(target=self._resolve_worker, args=(value,), daemon=True).start()

    def _resolve_worker(self, value: str) -> None:
        try:
            steam_id = core.resolve_steam_id_from_text(value)
            self.queue.put(("resolved", core.fetch_steam_profile(steam_id)))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def transfer(self) -> None:
        if not self.source_save.get().strip() or not self.target_steamid.get().strip():
            messagebox.showerror("Transfer Save", "Choose a source save and target SteamID first.")
            return
        args = argparse.Namespace(
            source_save=self.source_save.get().strip(),
            target_steamid=self.target_steamid.get().strip(),
            output=self.output_path.get().strip() or None,
            source_steamid=self.source_steamid.get().strip() or None,
            party_suffix=self.party_suffix.get().strip() or core.DEFAULT_PARTY_SUFFIX,
            no_payload_rewrite=not self.rewrite_payload.get(),
            copy_original_backup=self.copy_backup.get(),
        )
        self.status.configure(text="Transferring...")
        threading.Thread(target=self._transfer_worker, args=(args,), daemon=True).start()

    def _transfer_worker(self, args: argparse.Namespace) -> None:
        try:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                core.transfer_save(args)
            self.queue.put(("done", buffer.getvalue()))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def load_editor_save(self) -> None:
        if not self.source_save.get().strip():
            self.browse_source()
        if not self.source_save.get().strip():
            return
        self.status.configure(text="Loading save...")
        threading.Thread(target=self._load_editor_worker, daemon=True).start()

    def _load_editor_worker(self) -> None:
        try:
            plaintext, profile, steam_id = core.decrypt_save_file(
                self.source_save.get().strip(),
                self.source_steamid.get().strip() or None,
                self.party_suffix.get().strip() or core.DEFAULT_PARTY_SUFFIX,
            )
            entries = core.parse_runtime_inventory(plaintext)
            self.queue.put(("editor_loaded", (plaintext, profile.name, steam_id, entries)))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def render_inventory(self) -> None:
        self.capture_visible_inventory()
        for child in self.inventory_scroll.winfo_children():
            child.destroy()
        self.inventory_inputs.clear()
        search = self.editor_search.get().strip().lower()
        category = self.editor_category.get()
        filtered = [e for e in self.inventory_entries if (category == "All" or e.category == category) and (not search or search in e.name.lower())]
        self.editor_summary.configure(text=f"{len(filtered)} shown / {len(self.inventory_entries)} editable runtimeInventory values")
        for entry in filtered:
            row = ctk.CTkFrame(self.inventory_scroll, fg_color=PANEL, corner_radius=14)
            row.pack(fill="x", padx=4, pady=5)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=entry.category, width=95, text_color=MUTED).grid(row=0, column=0, padx=(14, 8), pady=10)
            ctk.CTkLabel(row, text=entry.name, font=("Segoe UI", 14, "bold"), text_color=TEXT).grid(row=0, column=1, sticky="w", pady=10)
            value = ctk.CTkEntry(row, width=140, height=36)
            value.insert(0, str(self.inventory_values.get(entry.offset, entry.value)))
            value.grid(row=0, column=2, padx=14, pady=10)
            self.inventory_inputs[entry.offset] = value

    def capture_visible_inventory(self) -> None:
        for offset, widget in list(self.inventory_inputs.items()):
            raw = widget.get().strip()
            if raw:
                self.inventory_values[offset] = int(raw)

    def save_editor_copy(self) -> None:
        if self.plaintext is None:
            messagebox.showerror("Save Editor", "Load a save first.")
            return
        output = self.output_path.get().strip() or self.source_save.get().strip()
        output = filedialog.asksaveasfilename(
            title="Save edited Far Far West save",
            initialfile=Path(output).name,
            initialdir=str(Path(output).parent),
            defaultextension=".save",
            filetypes=[("Far Far West saves", "*.save"), ("All files", "*.*")],
        )
        if not output:
            return
        try:
            self.capture_visible_inventory()
            edited = core.write_inventory_values(self.plaintext, self.inventory_values)
            path = core.save_edited_plaintext(
                output,
                edited,
                self.loaded_steam_id,
                self.party_suffix.get().strip() or core.DEFAULT_PARTY_SUFFIX,
                self.crypto_profile,
                create_backup=True,
            )
            self.write_log(f"Edited save written: {path}")
            messagebox.showinfo("Save Editor", f"Edited save written:\n{path}")
        except Exception as exc:
            messagebox.showerror("Save Editor", str(exc))

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "profile":
                    account = payload
                    self.profiles[account.steam_id] = account
                    self.avatars.pop(account.steam_id, None)
                    self.render_accounts()
                elif kind == "resolved":
                    account = payload
                    self.profiles[account.steam_id] = account
                    if all(a.steam_id != account.steam_id for a in self.accounts):
                        self.accounts.insert(0, account)
                    self.target_steamid.set(account.steam_id)
                    self.set_default_output()
                    self.render_accounts()
                    self.status.configure(text="Profile resolved")
                elif kind == "editor_loaded":
                    self.plaintext, self.crypto_profile, self.loaded_steam_id, self.inventory_entries = payload
                    self.inventory_values = {entry.offset: entry.value for entry in self.inventory_entries}
                    cats = ["All"] + sorted({e.category for e in self.inventory_entries})
                    self.category_menu.configure(values=cats)
                    self.editor_category.set("All")
                    self.render_inventory()
                    self.status.configure(text="Save loaded")
                    self.show_page("Editor")
                    self.write_log(f"Loaded {len(self.inventory_entries)} editable inventory values using {self.crypto_profile}.")
                elif kind == "done":
                    self.status.configure(text="Transfer complete")
                    self.write_log(str(payload).strip())
                    messagebox.showinfo("Transfer complete", "Transferred save was written successfully.")
                else:
                    self.status.configure(text="Error")
                    self.write_log(f"Error: {payload}")
                    messagebox.showerror("Far Far West Save Studio", str(payload))
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def write_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
