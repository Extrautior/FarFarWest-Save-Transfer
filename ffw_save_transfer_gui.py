#!/usr/bin/env python3
from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ffw_save_transfer as core


class SaveTransferApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Far Far West Save Transfer")
        self.geometry("760x560")
        self.minsize(700, 520)

        self.accounts: list[core.SteamAccount] = []
        self.worker_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self.source_save = tk.StringVar()
        self.source_steamid = tk.StringVar()
        self.target_steamid = tk.StringVar()
        self.output_path = tk.StringVar()
        self.party_suffix = tk.StringVar(value=core.DEFAULT_PARTY_SUFFIX)
        self.rewrite_payload = tk.BooleanVar(value=True)
        self.copy_backup = tk.BooleanVar(value=False)
        self.profile_input = tk.StringVar()
        self.status = tk.StringVar(value="Ready.")

        self._build_ui()
        self.refresh_accounts()
        self.after(150, self._poll_worker_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, padding=16)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(1, weight=1)
        root.rowconfigure(7, weight=1)

        title = ttk.Label(root, text="Far Far West Save Transfer", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(root, text="Old save").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.source_save).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(root, text="Browse", command=self.browse_source).grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(root, text="Source SteamID").grid(row=2, column=0, sticky="w", pady=4)
        source_row = ttk.Frame(root)
        source_row.grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        source_row.columnconfigure(0, weight=1)
        ttk.Entry(source_row, textvariable=self.source_steamid).grid(row=0, column=0, sticky="ew")
        ttk.Button(source_row, text="From filename", command=self.source_from_filename).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(root, text="Target account").grid(row=3, column=0, sticky="w", pady=4)
        target_row = ttk.Frame(root)
        target_row.grid(row=3, column=1, columnspan=2, sticky="ew", pady=4)
        target_row.columnconfigure(0, weight=1)
        self.account_combo = ttk.Combobox(target_row, state="readonly")
        self.account_combo.grid(row=0, column=0, sticky="ew")
        self.account_combo.bind("<<ComboboxSelected>>", self.pick_account)
        ttk.Button(target_row, text="Refresh", command=self.refresh_accounts).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(root, text="Target SteamID").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.target_steamid).grid(row=4, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(root, text="Profile URL / vanity").grid(row=5, column=0, sticky="w", pady=4)
        profile_row = ttk.Frame(root)
        profile_row.grid(row=5, column=1, columnspan=2, sticky="ew", pady=4)
        profile_row.columnconfigure(0, weight=1)
        ttk.Entry(profile_row, textvariable=self.profile_input).grid(row=0, column=0, sticky="ew")
        ttk.Button(profile_row, text="Resolve", command=self.resolve_profile).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(root, text="Output").grid(row=6, column=0, sticky="w", pady=4)
        output_row = ttk.Frame(root)
        output_row.grid(row=6, column=1, columnspan=2, sticky="ew", pady=4)
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_path).grid(row=0, column=0, sticky="ew")
        ttk.Button(output_row, text="Save as", command=self.browse_output).grid(row=0, column=1, padx=(8, 0))

        options = ttk.LabelFrame(root, text="Options", padding=10)
        options.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(12, 8))
        options.columnconfigure(1, weight=1)

        ttk.Label(options, text="Party suffix").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(options, textvariable=self.party_suffix).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(options, text="Replace old SteamID text inside decrypted save", variable=self.rewrite_payload).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(options, text="Copy original save backup before transfer", variable=self.copy_backup).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        self.log = tk.Text(options, height=9, wrap="word")
        self.log.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        options.rowconfigure(3, weight=1)

        bottom = ttk.Frame(root)
        bottom.grid(row=8, column=0, columnspan=3, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status).grid(row=0, column=0, sticky="w")
        ttk.Button(bottom, text="Transfer Save", command=self.transfer).grid(row=0, column=1, sticky="e")

    def browse_source(self) -> None:
        initial = str(core.SAVE_DIR) if core.SAVE_DIR.exists() else str(Path.home())
        path = filedialog.askopenfilename(title="Choose old Far Far West save", initialdir=initial, filetypes=[("Far Far West saves", "*.save"), ("All files", "*.*")])
        if path:
            self.source_save.set(path)
            self.source_from_filename(silent=True)
            if not self.output_path.get().strip() and self.target_steamid.get().strip():
                self.set_default_output()

    def browse_output(self) -> None:
        target = self.target_steamid.get().strip() or "target"
        path = filedialog.asksaveasfilename(title="Choose transferred save output", initialfile=f"{target}.save", defaultextension=".save", filetypes=[("Far Far West saves", "*.save"), ("All files", "*.*")])
        if path:
            self.output_path.set(path)

    def source_from_filename(self, silent: bool = False) -> None:
        try:
            path = Path(self.source_save.get().strip())
            self.source_steamid.set(core.infer_steam_id(path))
            if not silent:
                self.write_log(f"Source SteamID found: {self.source_steamid.get()}")
        except Exception as exc:  # noqa: BLE001
            if not silent:
                messagebox.showerror("Source SteamID", str(exc))

    def refresh_accounts(self) -> None:
        self.accounts = core.discover_steam_accounts()
        labels = [account.label for account in self.accounts]
        self.account_combo["values"] = labels
        if labels:
            self.account_combo.current(0)
            self.pick_account()
            self.write_log(f"Found {len(labels)} SteamID candidate(s).")
        else:
            self.account_combo.set("")
            self.write_log("No local Steam accounts found. Paste a SteamID64 or resolve a profile URL.")

    def pick_account(self, _event: object | None = None) -> None:
        index = self.account_combo.current()
        if 0 <= index < len(self.accounts):
            self.target_steamid.set(self.accounts[index].steam_id)
            self.set_default_output()

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
        self.status.set("Resolving Steam profile...")
        threading.Thread(target=self._resolve_profile_worker, args=(value,), daemon=True).start()

    def _resolve_profile_worker(self, value: str) -> None:
        try:
            steam_id = core.resolve_steam_id_from_text(value)
            self.worker_queue.put(("resolved", steam_id))
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
        self.status.set("Transferring save...")
        self.write_log("Starting transfer...")
        threading.Thread(target=self._transfer_worker, args=(args,), daemon=True).start()

    def _transfer_worker(self, args: argparse.Namespace) -> None:
        try:
            import contextlib
            import io

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                core.transfer_save(args)
            self.worker_queue.put(("done", buffer.getvalue()))
        except Exception as exc:  # noqa: BLE001
            self.worker_queue.put(("error", str(exc)))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                kind, message = self.worker_queue.get_nowait()
                if kind == "resolved":
                    self.target_steamid.set(message)
                    self.set_default_output()
                    self.status.set("Resolved SteamID.")
                    self.write_log(f"Resolved target SteamID: {message}")
                elif kind == "done":
                    self.status.set("Transfer complete.")
                    self.write_log(message.strip())
                    messagebox.showinfo("Transfer complete", "Transferred save was written successfully.")
                else:
                    self.status.set("Error.")
                    self.write_log(f"Error: {message}")
                    messagebox.showerror("Far Far West Save Transfer", message)
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
