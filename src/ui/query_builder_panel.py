# src/ui/query_builder_panel.py
"""
Visual query builder for metadata search (Phase 11).
"""

from __future__ import annotations

import copy
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import customtkinter as ctk

from src.core.metadata_search import Combiner, QueryCondition, filter_value_suggestions

_TEXT_OPS = ["=", "!=", "contains", "starts with", "ends with"]
_NUM_OPS = ["=", "!=", ">", "<", ">=", "<="]
_AUTO_OPS = list(dict.fromkeys(_TEXT_OPS + _NUM_OPS))
_COMBO_SHOW = 400


class QueryBuilderPanel(ctk.CTkFrame):
    """
    Dynamic conditions with AND/OR connectors, field/operator/type controls, and actions.

    The primary Search action lives on the parent dialog footer so it is always visible;
    this panel only manages conditions (add / clear).

    When ``value_suggestions`` is provided, the value control becomes an editable
    combobox populated from distinct database values for the selected column.
    """

    def __init__(
        self,
        master: Any,
        *,
        metadata_fields: List[str],
        on_clear: Callable[[], None],
        value_suggestions: Optional[Callable[[str], Tuple[List[str], bool]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._fields = list(metadata_fields)
        self._on_clear = on_clear
        self._value_suggestions = value_suggestions

        self._rows: List[Dict[str, Any]] = []
        self._combiners: List[str] = []
        self._live_row_vars: List[Dict[str, Any]] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._rows_frame = ctk.CTkScrollableFrame(self, height=220)
        self._rows_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._summary = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray70",
            anchor="w",
            justify="left",
        )
        self._summary.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 4))
        ctk.CTkButton(
            btn_row,
            text="+ Add condition",
            width=130,
            command=self._add_condition,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row,
            text="Clear conditions",
            width=130,
            fg_color="gray40",
            command=self._clear_all,
        ).pack(side="left", padx=4)

        if self._fields:
            self._rows.append(self._default_row_dict())
        self._render()

    def set_metadata_fields(self, fields: List[str]) -> None:
        """Refresh when configuration changes."""
        self._flush_live_row_state()
        self._fields = list(fields)
        for row in self._rows:
            if row["field"] not in self._fields and self._fields:
                row["field"] = self._fields[0]
        if not self._rows and self._fields:
            self._rows.append(self._default_row_dict())
        self._render()

    @staticmethod
    def _default_row_dict() -> Dict[str, Any]:
        return {
            "field": "",
            "field_type": "auto",
            "operator": "=",
            "value": "",
            "case_sensitive": False,
        }

    def _ops_for_type(self, ft: str) -> List[str]:
        if ft in ("numeric", "date"):
            return list(_NUM_OPS)
        if ft == "text":
            return list(_TEXT_OPS)
        return list(_AUTO_OPS)

    def _load_suggestions(self, field: str) -> Tuple[List[str], bool]:
        if self._value_suggestions is None:
            return [], False
        name = (field or "").strip()
        if not name or name == "(no columns)":
            return [], False
        try:
            values, truncated = self._value_suggestions(name)
            return list(values), bool(truncated)
        except Exception:
            return [], False

    def _add_condition(self) -> None:
        self._flush_live_row_state()
        self._rows.append(self._default_row_dict())
        if len(self._rows) >= 2 and len(self._combiners) < len(self._rows) - 1:
            self._combiners.append("AND")
        self._render()

    def _remove_condition(self, index: int) -> None:
        self._flush_live_row_state()
        n = len(self._rows)
        if index < 0 or index >= n:
            return
        self._rows.pop(index)
        if n > 1 and self._combiners:
            if index == 0:
                self._combiners.pop(0)
            elif index == n - 1:
                self._combiners.pop()
            else:
                self._combiners.pop(index)
        while len(self._combiners) > max(0, len(self._rows) - 1):
            self._combiners.pop()
        if not self._rows and self._fields:
            self._rows.append(self._default_row_dict())
        self._render()

    def _clear_all(self) -> None:
        self._rows = []
        self._combiners = []
        self._live_row_vars = []
        if self._fields:
            self._rows.append(self._default_row_dict())
        self._render()
        self._on_clear()

    def _flush_live_row_state(self) -> None:
        """Copy live Entry / OptionMenu vars into ``_rows`` before reading conditions."""
        for index, live in enumerate(self._live_row_vars):
            if index >= len(self._rows):
                break
            self._rows[index]["field"] = live["field"].get()
            self._rows[index]["field_type"] = live["field_type"].get()
            self._rows[index]["operator"] = live["operator"].get()
            self._rows[index]["value"] = live["value"].get()
            self._rows[index]["case_sensitive"] = bool(live["case_sensitive"].get())
        if self._live_row_vars and len(self._rows) > 1:
            combiner_vars = [
                live.get("combiner")
                for live in self._live_row_vars[1:]
                if live.get("combiner") is not None
            ]
            if combiner_vars:
                self._sync_combiners_from_vars(combiner_vars)

    def get_conditions(self) -> List[QueryCondition]:
        self._flush_live_row_state()
        out: List[QueryCondition] = []
        for row in self._rows:
            field = (row.get("field") or "").strip()
            if not field or field == "(no columns)":
                continue
            out.append(
                QueryCondition(
                    field=field,
                    operator=str(row.get("operator") or "="),
                    value=str(row.get("value") or ""),
                    field_type=str(row.get("field_type") or "auto"),  # type: ignore[arg-type]
                    case_sensitive=bool(row.get("case_sensitive")),
                )
            )
        return out

    def get_combiners(self) -> List[Combiner]:
        conds = self.get_conditions()
        if len(conds) <= 1:
            return []
        need = len(conds) - 1
        combs = copy.copy(self._combiners)
        while len(combs) < need:
            combs.append("AND")
        return [c if c in ("AND", "OR") else "AND" for c in combs[:need]]

    def _sync_combiners_from_vars(self, vars_list: List[tk.StringVar]) -> None:
        self._combiners = [v.get() if v.get() in ("AND", "OR") else "AND" for v in vars_list]

    def _apply_value_combo_values(
        self,
        value_combo: ctk.CTkComboBox,
        vvar: tk.StringVar,
        all_values: Sequence[str],
        *,
        needle: Optional[str] = None,
    ) -> None:
        """Update combobox dropdown options without clobbering typed text."""
        text = vvar.get() if needle is None else needle
        filtered = filter_value_suggestions(all_values, text or "", max_show=_COMBO_SHOW)
        if not filtered:
            filtered = [text] if (text or "").strip() else [""]
        current = vvar.get()
        value_combo.configure(values=filtered)
        if vvar.get() != current:
            vvar.set(current)

    def _render(self) -> None:
        for w in self._rows_frame.winfo_children():
            w.destroy()
        self._live_row_vars = []

        if not self._fields:
            ctk.CTkLabel(
                self._rows_frame,
                text="No metadata columns were stored in this database. "
                "Include metadata columns in Configure Spreadsheet and rebuild the database.",
                text_color="orange",
            ).pack(anchor="w", padx=4, pady=4)
            self._summary.configure(text="")
            return

        field_vals = self._fields
        combiner_vars: List[tk.StringVar] = []
        for i, row in enumerate(self._rows):
            live: Dict[str, Any] = {}
            if i > 0:
                cvar = tk.StringVar(
                    value=self._combiners[i - 1]
                    if i - 1 < len(self._combiners)
                    else "AND"
                )
                combiner_vars.append(cvar)
                live["combiner"] = cvar

                def _on_comb_change(_v: str, vars_list: List[tk.StringVar] = combiner_vars) -> None:
                    self._sync_combiners_from_vars(vars_list)
                    self._update_summary_only()

                ctk.CTkOptionMenu(
                    self._rows_frame,
                    values=["AND", "OR"],
                    variable=cvar,
                    width=72,
                    command=_on_comb_change,
                ).pack(anchor="w", padx=4, pady=(4, 0))

            fr = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
            fr.pack(fill="x", padx=2, pady=2)
            fr.grid_columnconfigure(3, weight=1)

            if not row.get("field"):
                row["field"] = field_vals[0]

            fvar = tk.StringVar(value=row["field"])
            tvar = tk.StringVar(value=row.get("field_type", "auto"))
            opvar = tk.StringVar(value=row.get("operator", "="))
            vvar = tk.StringVar(value=str(row.get("value", "")))
            case_var = tk.IntVar(value=1 if row.get("case_sensitive") else 0)

            suggestions, truncated = self._load_suggestions(row["field"])
            live.update(
                {
                    "field": fvar,
                    "field_type": tvar,
                    "operator": opvar,
                    "value": vvar,
                    "case_sensitive": case_var,
                    "all_suggestions": suggestions,
                    "suggestions_truncated": truncated,
                }
            )
            self._live_row_vars.append(live)

            def _save(
                idx: int,
                fv: tk.StringVar,
                tv: tk.StringVar,
                ov: tk.StringVar,
                vv: tk.StringVar,
                cv: tk.IntVar,
            ) -> None:
                self._rows[idx]["field"] = fv.get()
                self._rows[idx]["field_type"] = tv.get()
                self._rows[idx]["operator"] = ov.get()
                self._rows[idx]["value"] = vv.get()
                self._rows[idx]["case_sensitive"] = bool(cv.get())
                if combiner_vars:
                    self._sync_combiners_from_vars(combiner_vars)
                self._update_summary_only()

            def _on_field_change(
                _choice: str,
                idx: int = i,
                fv: tk.StringVar = fvar,
                tv: tk.StringVar = tvar,
                ov: tk.StringVar = opvar,
                vv: tk.StringVar = vvar,
                cv: tk.IntVar = case_var,
                live_ref: Dict[str, Any] = live,
            ) -> None:
                _save(idx, fv, tv, ov, vv, cv)
                new_field = fv.get()
                new_vals, new_trunc = self._load_suggestions(new_field)
                live_ref["all_suggestions"] = new_vals
                live_ref["suggestions_truncated"] = new_trunc
                vv.set("")
                self._rows[idx]["value"] = ""
                value_combo = live_ref.get("value_combo")
                if value_combo is not None:
                    self._apply_value_combo_values(value_combo, vv, new_vals, needle="")
                self._update_summary_only()

            fcombo = ctk.CTkComboBox(
                fr,
                values=field_vals,
                variable=fvar,
                width=160,
                command=_on_field_change,
            )
            fcombo.grid(row=0, column=0, padx=2, sticky="w")

            def _on_type_change(_v: str, idx: int = i, tv: tk.StringVar = tvar) -> None:
                self._flush_live_row_state()
                self._rows[idx]["field_type"] = tv.get()
                self._fix_operator_for_row(idx)
                self._render()

            type_menu = ctk.CTkOptionMenu(
                fr,
                variable=tvar,
                values=["auto", "text", "numeric", "date"],
                width=88,
                command=_on_type_change,
            )
            type_menu.grid(row=0, column=1, padx=2, sticky="w")

            ops = self._ops_for_type(tvar.get())
            if opvar.get() not in ops:
                opvar.set(ops[0])
            op_menu = ctk.CTkOptionMenu(
                fr,
                variable=opvar,
                values=ops,
                width=120,
                command=lambda _v, idx=i, fv=fvar, tv=tvar, ov=opvar, vv=vvar, cv=case_var: _save(
                    idx, fv, tv, ov, vv, cv
                ),
            )
            op_menu.grid(row=0, column=2, padx=2, sticky="w")

            initial_values = filter_value_suggestions(
                suggestions,
                vvar.get(),
                max_show=_COMBO_SHOW,
            )
            if not initial_values:
                initial_values = [vvar.get()] if vvar.get().strip() else [""]

            value_combo = ctk.CTkComboBox(
                fr,
                values=initial_values,
                variable=vvar,
                width=200,
                command=lambda _c, idx=i, fv=fvar, tv=tvar, ov=opvar, vv=vvar, cv=case_var: _save(
                    idx, fv, tv, ov, vv, cv
                ),
            )
            value_combo.grid(row=0, column=3, padx=2, sticky="ew")
            live["value_combo"] = value_combo

            def _on_value_typed(
                _event: Optional[tk.Event] = None,
                idx: int = i,
                fv: tk.StringVar = fvar,
                tv: tk.StringVar = tvar,
                ov: tk.StringVar = opvar,
                vv: tk.StringVar = vvar,
                cv: tk.IntVar = case_var,
                live_ref: Dict[str, Any] = live,
                combo: ctk.CTkComboBox = value_combo,
            ) -> None:
                _save(idx, fv, tv, ov, vv, cv)
                all_vals = live_ref.get("all_suggestions") or []
                self._apply_value_combo_values(combo, vv, all_vals)

            value_combo.bind("<KeyRelease>", _on_value_typed)
            value_combo.bind("<FocusOut>", _on_value_typed)

            # Case-sensitive applies to text operators only (auto/text field types).
            if tvar.get() in ("auto", "text"):
                ctk.CTkCheckBox(
                    fr,
                    text="Aa",
                    variable=case_var,
                    width=36,
                    command=lambda idx=i, fv=fvar, tv=tvar, ov=opvar, vv=vvar, cv=case_var: _save(
                        idx, fv, tv, ov, vv, cv
                    ),
                ).grid(row=0, column=4, padx=2)
            else:
                case_var.set(0)
                row["case_sensitive"] = False

            ctk.CTkButton(
                fr,
                text="✕",
                width=28,
                fg_color="gray35",
                command=lambda idx=i: self._remove_condition(idx),
            ).grid(row=0, column=5, padx=2)

        if combiner_vars:
            self._sync_combiners_from_vars(combiner_vars)
        self._update_summary_only()

    def _fix_operator_for_row(self, index: int) -> None:
        ft = self._rows[index].get("field_type", "auto")
        ops = self._ops_for_type(ft)
        if self._rows[index].get("operator") not in ops:
            self._rows[index]["operator"] = ops[0]

    def _update_summary_only(self) -> None:
        conds = self.get_conditions()
        combs = self.get_combiners()
        if not conds:
            self._summary.configure(
                text="No active conditions — pick a column, then choose or type a value."
            )
            return
        parts: List[str] = []
        for i, c in enumerate(conds):
            if i > 0 and i - 1 < len(combs):
                parts.append(combs[i - 1])
            cs = " [Aa]" if c.case_sensitive else ""
            parts.append(f"{c.field} {c.operator} {c.value!r}{cs}")

        hint = ""
        if self._live_row_vars:
            live0 = self._live_row_vars[0]
            n_sug = len(live0.get("all_suggestions") or [])
            if live0.get("suggestions_truncated"):
                hint = f"  ·  {n_sug}+ distinct values (type to filter the list)"
            elif n_sug:
                hint = f"  ·  {n_sug} distinct value(s) available in the value list"
        self._summary.configure(text=" ".join(parts) + hint)
