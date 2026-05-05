#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import queue
import threading
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import ffw_save_transfer as core

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # pragma: no cover - release builds include Pillow.
    Image = ImageDraw = ImageTk = None


BG = "#0f172a"
PANEL = "#111827"
CARD = "#1f2937"
CARD_2 = "#273244"
TEXT = "#e5e7eb"
MUTED = "#9ca3af"
ACCENT = "#38bdf8"
OK = "#22c55e"
WARN = "#f59e0b"


EDITOR_GROUPS = [
    ("Inventory", "Items, quantities, unlock states, discovered gear."),
    ("Item Progression", "Item level, item XP, upgrade tier, upgrade cost values."),
    ("Character Stats", "Core stats, stat counters, challenge counters."),
    ("Jokers & Loadouts", "Joker inventory, equipped jokers, selected loadout slots."),
    ("Rewards & Challenges", "Rewarded challenges, completion flags, claim states."),
    ("Save Maintenance", "Backups, SteamID rewrite, re-encryption, raw inspection."),
]


class ModernButton(tk.Button):
    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        kwargs.setdefault("bg", ACCENT)
        kwargs.setdefault("fg", "#06121f")
        kwargs.setdefault("activebackground", "#7dd3fc")
        kwargs.setdefault("activeforeground", "#06121f")
        kwargs.setdefault("relief", "flat")
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("padx", 14)
        kwargs.setdefault("pady", 8)
        kwargs.setdefault("font", ("Segoe UI", 10, "bold"))
        super().__init__(master, **kwargs)


class SaveTransferApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Far Far West Save Transfer")
        self.geometry("1060x720")
        self.minsize(980, 640)
        self.configure(bg=BG)

        self.accounts: list[core.SteamAccount] = []
        self.profile_accounts: dict[str, core.SteamAccount] = {}
        self.avatar_images: dict[str, tk.PhotoImage] = {}
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.source_save = tk.StringVar()
        self.source_steamid = tk.StringVar()
        self.target_steamid = tk.StringVar()
        self.output_path = tk.StringVar()
        self.party_suffix = tk.StringVar(value=core.DEFAULT_PARTY_SUFFIX)
        self.rewrite_payload = tk.BooleanVar(value=True)
        self.copy_backup = tk.BooleanVar(value=False)
        self.profile_input = tk.StringVar()
        self.status = tk.StringVar(value="Ready")

        self._configure_styles()
        self._build_ui()
        self.refresh_accounts()
        self.after(150, self._poll_worker_queue)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=CARD, bordercolor=CARD, lightcolor=CARD, darkcolor=CARD)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(18, 10), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])
        style.configure("TEntry", padding=8, fieldbackground="#0b1220", foreground=TEXT, borderwidth=1)
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.configure("TLabelframe", background=PANEL, foreground=TEXT, bordercolor=CARD_2)
        style.configure("TLabelframe.Label", background=PANEL, foreground=TEXT)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=BG, padx=22, pady=18)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="Far Far West Save Transfer", bg=BG, fg=TEXT, font=("Segoe UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="Transfer saves, discover SteamIDs, and inspect decrypted save structure.", bg=BG, fg=MUTED, font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w")
        tk.Label(header, textvariable=self.status, bg=BG, fg=ACCENT, font=("Segoe UI", 10, "bold")).grid(row=0, column=1, rowspan=2, sticky="e")

        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 22))
        self.transfer_tab = self._tab("Transfer")
        self.accounts_tab = self._tab("Steam Accounts")
        self.editor_tab = self._tab("Save Editor")
        self.activity_tab = self._tab("Activity")

        self._build_transfer_tab()
        self._build_accounts_tab()
        self._build_editor_tab()
        self._build_activity_tab()

    def _tab(self, title: str) -> tk.Frame:
        frame = tk.Frame(self.tabs, bg=PANEL, padx=18, pady=18)
        self.tabs.add(frame, text=title)
        return frame

    def _field(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar, button_text: str | None = None, command: object | None = None) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="w", pady=(8, 3))
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.grid(row=row + 1, column=0, sticky="ew", pady=(0, 6))
        wrap.columnconfigure(0, weight=1)
        ttk.Entry(wrap, textvariable=variable).grid(row=0, column=0, sticky="ew")
        if button_text:
            ModernButton(wrap, text=button_text, command=command).grid(row=0, column=1, padx=(8, 0))

    def _build_transfer_tab(self) -> None:
        self.transfer_tab.columnconfigure(0, weight=2)
        self.transfer_tab.columnconfigure(1, weight=1)
        left = tk.Frame(self.transfer_tab, bg=PANEL)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)

        self._field(left, 0, "Old save file", self.source_save, "Browse", self.browse_source)
        self._field(left, 2, "Source SteamID64", self.source_steamid, "From filename", self.source_from_filename)
        self._field(left, 4, "Target SteamID64", self.target_steamid, None, None)
        self._field(left, 6, "Output save file", self.output_path, "Save as", self.browse_output)
        self._field(left, 8, "Party suffix", self.party_suffix, None, None)

        opts = tk.Frame(left, bg=PANEL)
        opts.grid(row=10, column=0, sticky="ew", pady=8)
        tk.Checkbutton(opts, text="Replace old SteamID text inside decrypted payload", variable=self.rewrite_payload, bg=PANEL, fg=TEXT, selectcolor=CARD, activebackground=PANEL, activeforeground=TEXT).grid(row=0, column=0, sticky="w")
        tk.Checkbutton(opts, text="Copy original save backup before transfer", variable=self.copy_backup, bg=PANEL, fg=TEXT, selectcolor=CARD, activebackground=PANEL, activeforeground=TEXT).grid(row=1, column=0, sticky="w")
        ModernButton(left, text="Transfer Save", command=self.transfer, bg=OK, activebackground="#86efac").grid(row=11, column=0, sticky="ew", pady=(12, 0))

        right = tk.Frame(self.transfer_tab, bg=CARD, padx=16, pady=16)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        tk.Label(right, text="Target Account", bg=CARD, fg=TEXT, font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.selected_avatar = tk.Label(right, bg=CARD)
        self.selected_avatar.grid(row=1, column=0, sticky="w", pady=(14, 8))
        self.selected_account_label = tk.Label(right, text="Choose an account below", bg=CARD, fg=TEXT, justify="left", wraplength=270, font=("Segoe UI", 10, "bold"))
        self.selected_account_label.grid(row=2, column=0, sticky="w")
        ModernButton(right, text="Refresh Accounts", command=self.refresh_accounts).grid(row=3, column=0, sticky="ew", pady=(18, 8))
        ttk.Entry(right, textvariable=self.profile_input).grid(row=4, column=0, sticky="ew", pady=(6, 8))
        ModernButton(right, text="Resolve Profile URL / Vanity", command=self.resolve_profile).grid(row=5, column=0, sticky="ew")

    def _build_accounts_tab(self) -> None:
        self.accounts_tab.columnconfigure(0, weight=1)
        top = tk.Frame(self.accounts_tab, bg=PANEL)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top.columnconfigure(0, weight=1)
        tk.Label(top, text="Steam Accounts", bg=PANEL, fg=TEXT, font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ModernButton(top, text="Refresh", command=self.refresh_accounts).grid(row=0, column=1, sticky="e")

        self.account_canvas = tk.Canvas(self.accounts_tab, bg=PANEL, highlightthickness=0)
        self.account_canvas.grid(row=1, column=0, sticky="nsew")
        self.accounts_tab.rowconfigure(1, weight=1)
        self.account_frame = tk.Frame(self.account_canvas, bg=PANEL)
        self.account_canvas.create_window((0, 0), window=self.account_frame, anchor="nw")
        self.account_frame.bind("<Configure>", lambda _e: self.account_canvas.configure(scrollregion=self.account_canvas.bbox("all")))

    def _build_editor_tab(self) -> None:
        self.editor_tab.columnconfigure(0, weight=1)
        self.editor_tab.columnconfigure(1, weight=1)
        tk.Label(self.editor_tab, text="Save Editor", bg=PANEL, fg=TEXT, font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(self.editor_tab, text="The editor is organized around the known save-editor feature areas. Safe inspection is active now; deep value editing needs a game-specific GVAS schema before it should write changes.", bg=PANEL, fg=MUTED, wraplength=900, justify="left").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 16))

        for i, (title, desc) in enumerate(EDITOR_GROUPS):
            card = tk.Frame(self.editor_tab, bg=CARD, padx=14, pady=12)
            card.grid(row=2 + i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 8, 8 if i % 2 == 0 else 0), pady=8)
            tk.Label(card, text=title, bg=CARD, fg=TEXT, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
            tk.Label(card, text=desc, bg=CARD, fg=MUTED, wraplength=390, justify="left").grid(row=1, column=0, sticky="w", pady=(4, 8))
            state = "Active" if title == "Save Maintenance" else "Planned"
            color = OK if state == "Active" else WARN
            tk.Label(card, text=state, bg=color, fg="#08111f", padx=8, pady=3, font=("Segoe UI", 8, "bold")).grid(row=0, column=1, sticky="e", padx=(8, 0))
            card.columnconfigure(0, weight=1)

        inspect = tk.Frame(self.editor_tab, bg=CARD_2, padx=14, pady=12)
        inspect.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        inspect.columnconfigure(0, weight=1)
        tk.Label(inspect, text="Safe Save Inspector", bg=CARD_2, fg=TEXT, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ModernButton(inspect, text="Decrypt & Inspect Current Save", command=self.inspect_current_save).grid(row=0, column=1, sticky="e")
        self.inspect_text = tk.Text(inspect, height=7, wrap="word", bg="#0b1220", fg=TEXT, insertbackground=TEXT, relief="flat", padx=10, pady=10)
        self.inspect_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _build_activity_tab(self) -> None:
        self.activity_tab.columnconfigure(0, weight=1)
        self.activity_tab.rowconfigure(1, weight=1)
        tk.Label(self.activity_tab, text="Activity Log", bg=PANEL, fg=TEXT, font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.log = tk.Text(self.activity_tab, wrap="word", bg="#0b1220", fg=TEXT, insertbackground=TEXT, relief="flat", padx=12, pady=12)
        self.log.grid(row=1, column=0, sticky="nsew")

    def browse_source(self) -> None:
        initial = str(core.SAVE_DIR) if core.SAVE_DIR.exists() else str(Path.home())
        path = filedialog.askopenfilename(title="Choose old Far Far West save", initialdir=initial, filetypes=[("Far Far West saves", "*.save"), ("All files", "*.*")])
        if path:
            self.source_save.set(path)
            self.source_from_filename(silent=True)
            self.set_default_output()

    def browse_output(self) -> None:
        target = self.target_steamid.get().strip() or "target"
        path = filedialog.asksaveasfilename(title="Choose transferred save output", initialfile=f"{target}.save", defaultextension=".save", filetypes=[("Far Far West saves", "*.save"), ("All files", "*.*")])
        if path:
            self.output_path.set(path)

    def source_from_filename(self, silent: bool = False) -> None:
        try:
            self.source_steamid.set(core.infer_steam_id(Path(self.source_save.get().strip())))
            if not silent:
                self.write_log(f"Source SteamID found: {self.source_steamid.get()}")
        except Exception as exc:  # noqa: BLE001
            if not silent:
                messagebox.showerror("Source SteamID", str(exc))

    def refresh_accounts(self) -> None:
        self.accounts = core.discover_steam_accounts()
        self._render_accounts()
        self.write_log(f"Found {len(self.accounts)} SteamID candidate(s).")
        for account in self.accounts:
            threading.Thread(target=self._fetch_profile_worker, args=(account.steam_id,), daemon=True).start()

    def _render_accounts(self) -> None:
        for child in self.account_frame.winfo_children():
            child.destroy()
        for i, account in enumerate(self.accounts):
            card = tk.Frame(self.account_frame, bg=CARD, padx=12, pady=10)
            card.grid(row=i // 2, column=i % 2, sticky="ew", padx=8, pady=8)
            card.columnconfigure(1, weight=1)
            avatar = tk.Label(card, image=self._avatar_for(account), bg=CARD)
            avatar.grid(row=0, column=0, rowspan=2, padx=(0, 12))
            name = self.profile_accounts.get(account.steam_id, account).persona_name or account.label.split(" - ")[0]
            tk.Label(card, text=name, bg=CARD, fg=TEXT, font=("Segoe UI", 11, "bold")).grid(row=0, column=1, sticky="w")
            tk.Label(card, text=f"{account.steam_id}\n{account.source}", bg=CARD, fg=MUTED, justify="left", wraplength=360).grid(row=1, column=1, sticky="w")
            ModernButton(card, text="Use", command=lambda a=account: self.use_account(a)).grid(row=0, column=2, rowspan=2, padx=(12, 0))
        self._update_selected_account()

    def use_account(self, account: core.SteamAccount) -> None:
        self.target_steamid.set(account.steam_id)
        self.set_default_output()
        self.tabs.select(self.transfer_tab)
        self._update_selected_account()

    def _update_selected_account(self) -> None:
        steam_id = self.target_steamid.get().strip()
        account = self.profile_accounts.get(steam_id) or next((a for a in self.accounts if a.steam_id == steam_id), None)
        if account:
            self.selected_avatar.configure(image=self._avatar_for(account))
            self.selected_account_label.configure(text=f"{account.persona_name or account.label}\n{account.steam_id}")
        else:
            self.selected_avatar.configure(image=self._placeholder_avatar("?"))
            self.selected_account_label.configure(text="Choose an account below")

    def _fetch_profile_worker(self, steam_id: str) -> None:
        try:
            self.worker_queue.put(("profile", core.fetch_steam_profile(steam_id)))
        except Exception:
            pass

    def _avatar_for(self, account: core.SteamAccount) -> tk.PhotoImage:
        if account.steam_id in self.avatar_images:
            return self.avatar_images[account.steam_id]
        profiled = self.profile_accounts.get(account.steam_id, account)
        if profiled.avatar_url and Image is not None and ImageTk is not None:
            try:
                with urllib.request.urlopen(profiled.avatar_url, timeout=8) as response:
                    image_bytes = response.read()
                image = Image.open(io.BytesIO(image_bytes)).resize((56, 56))
                photo = ImageTk.PhotoImage(image)
                self.avatar_images[account.steam_id] = photo
                return photo
            except Exception:
                pass
        photo = self._placeholder_avatar((profiled.persona_name or profiled.label or "?")[:1].upper())
        self.avatar_images[account.steam_id] = photo
        return photo

    def _placeholder_avatar(self, letter: str) -> tk.PhotoImage:
        key = f"placeholder:{letter}"
        if key in self.avatar_images:
            return self.avatar_images[key]
        if Image is not None and ImageTk is not None:
            image = Image.new("RGB", (56, 56), CARD_2)
            draw = ImageDraw.Draw(image)
            draw.ellipse((0, 0, 55, 55), fill="#164e63")
            draw.text((28, 28), letter, fill=TEXT, anchor="mm")
            photo = ImageTk.PhotoImage(image)
        else:
            photo = tk.PhotoImage(width=56, height=56)
            photo.put("#164e63", to=(0, 0, 56, 56))
        self.avatar_images[key] = photo
        return photo

    def set_default_output(self) -> None:
        target = self.target_steamid.get().strip()
        source = self.source_save.get().strip()
        if target and source:
            self.output_path.set(str(Path(source).with_name(f"{target}.save")))

    def resolve_profile(self) -> None:
        value = self.profile_input.get().strip()
        if not value:
            messagebox.showerror("Resolve SteamID", "Paste a Steam profile URL, vanity name, or SteamID64.")
            return
        self.status.set("Resolving profile")
        threading.Thread(target=self._resolve_profile_worker, args=(value,), daemon=True).start()

    def _resolve_profile_worker(self, value: str) -> None:
        try:
            steam_id = core.resolve_steam_id_from_text(value)
            profile = core.fetch_steam_profile(steam_id)
            self.worker_queue.put(("resolved", profile))
        except Exception as exc:  # noqa: BLE001
            self.worker_queue.put(("error", str(exc)))

    def transfer(self) -> None:
        source = self.source_save.get().strip()
        target = self.target_steamid.get().strip()
        if not source or not target:
            messagebox.showerror("Transfer Save", "Choose a source save and target SteamID first.")
            return
        args = argparse.Namespace(
            source_save=source,
            target_steamid=target,
            output=self.output_path.get().strip() or None,
            source_steamid=self.source_steamid.get().strip() or None,
            party_suffix=self.party_suffix.get().strip() or core.DEFAULT_PARTY_SUFFIX,
            no_payload_rewrite=not self.rewrite_payload.get(),
            copy_original_backup=self.copy_backup.get(),
        )
        self.status.set("Transferring")
        self.write_log("Starting transfer...")
        threading.Thread(target=self._transfer_worker, args=(args,), daemon=True).start()

    def _transfer_worker(self, args: argparse.Namespace) -> None:
        try:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                core.transfer_save(args)
            self.worker_queue.put(("done", buffer.getvalue()))
        except Exception as exc:  # noqa: BLE001
            self.worker_queue.put(("error", str(exc)))

    def inspect_current_save(self) -> None:
        source = self.source_save.get().strip()
        if not source:
            messagebox.showerror("Inspect Save", "Choose a source save first.")
            return
        try:
            info = core.inspect_save(source, self.source_steamid.get().strip() or None, self.party_suffix.get().strip() or core.DEFAULT_PARTY_SUFFIX)
            text = (
                f"Source SteamID: {info.source_steam_id}\n"
                f"Crypto profile: {info.crypto_profile}\n"
                f"Encrypted size: {info.encrypted_size:,} bytes\n"
                f"Decrypted size: {info.plaintext_size:,} bytes\n"
                f"GVAS offset: {info.gvas_offset}\n"
                f"SteamID occurrences: {info.steamid_ascii_count} ASCII, {info.steamid_utf16_count} UTF-16LE\n"
            )
            self.inspect_text.delete("1.0", "end")
            self.inspect_text.insert("end", text)
            self.write_log("Save inspection complete.")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Inspect Save", str(exc))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                kind, message = self.worker_queue.get_nowait()
                if kind == "profile":
                    account = message
                    self.profile_accounts[account.steam_id] = account
                    self.avatar_images.pop(account.steam_id, None)
                    self._render_accounts()
                elif kind == "resolved":
                    account = message
                    self.profile_accounts[account.steam_id] = account
                    if all(a.steam_id != account.steam_id for a in self.accounts):
                        self.accounts.insert(0, account)
                    self.target_steamid.set(account.steam_id)
                    self.set_default_output()
                    self.status.set("Profile resolved")
                    self._render_accounts()
                    self.write_log(f"Resolved {account.persona_name or account.label}: {account.steam_id}")
                elif kind == "done":
                    self.status.set("Transfer complete")
                    self.write_log(str(message).strip())
                    messagebox.showinfo("Transfer complete", "Transferred save was written successfully.")
                else:
                    self.status.set("Error")
                    self.write_log(f"Error: {message}")
                    messagebox.showerror("Far Far West Save Transfer", str(message))
        except queue.Empty:
            pass
        self.after(150, self._poll_worker_queue)

    def write_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")


def main() -> int:
    app = SaveTransferApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
