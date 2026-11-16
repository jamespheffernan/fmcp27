"""Bounded access to the native FM26 reader, with process and evidence checks."""

from __future__ import annotations

import ctypes
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import struct
import subprocess
import sys
import threading

from . import address_book
from . import players, world, virtual, database, staff, staff_attributes, contract_dates, wages, contract_status, contract_bonuses, player_profile, personality, player_health
from .reader import ReadStream, ReaderError
from . import player_injury_status
from . import stadium_changes, currencies, current_player_statistics
from . import archived_player_statistics, archive_stat_references, stats_archive
from . import competition_scorers, league_scorers, league_age_exemptions, player_registration_source
from . import performance_comparison, virtual_identity, team_player_selection
from . import cup_history, fixture_player_checks, fixture_signed_after_round, fixture_suspension
from . import player_injury_return
from . import live_tactical_assignments_source
from . import live_in_possession_source
from . import live_team_sheet_source
from . import prepared_tactics_source, prepared_tactics_fields
from . import prepared_tactic_formations, prepared_tactic_instructions, prepared_tactic_roles
from . import training_source, training_calendar, training_sessions
from . import shortlist_source, shortlist_members
from . import assessment_people, assessment_source, player_ban_source, player_fixture_suspensions
from decimal import Decimal, localcontext
from fractions import Fraction
from . import __version__, club_finance, recruitment, wage_contributions, contract_terms, loan_contracts, competitions, teams, competition_registrations, competition_stages, fixtures, stadiums, cities, geography, languages, local_regions, media_sources, weather


ROOT = Path(__file__).resolve().parent.parent


class BridgeError(RuntimeError):
    """An actionable error, surfaced as an MCP tool error."""


@dataclass(frozen=True)
class Process:
    pid: int
    executable: str
    started: str
    version: str
    bundle_id: str
    executable_stamp: str


def process_info(pid: int) -> Process | None:
    """Check the kernel executable path, not command-line substrings."""
    if sys.platform != "darwin":
        raise BridgeError("This native reader requires macOS.")
    lib = ctypes.CDLL("/usr/lib/libproc.dylib")
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(4096)
    if lib.proc_pidpath(pid, buffer, len(buffer)) <= 0:
        return None
    path = Path(os.fsdecode(buffer.value))
    if not re.fullmatch(r"Football Manager (26|27)|fm", path.name):
        return None
    if path.parent.name != "MacOS" or path.parent.parent.name != "Contents":
        return None
    try:
        contents = path.parent.parent
        with (contents / "Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        bundle_id = info.get("CFBundleIdentifier", "")
        if bundle_id not in {
            "com.SportsInteractive.FootballManager26",
            "com.SportsInteractive.FootballManager27",
        } or info.get("CFBundleExecutable") != path.name:
            return None
        stat = path.stat()
        stamp = f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"
        # `ps -o lstart` names the process start; it is asked once per process. A later call
        # reuses it while the kernel's start time (libproc, no subprocess) and the executable
        # are the same: the same pid with another start time is another process.
        key = (_start_time(lib, pid), str(path), stamp)
        cached = _PROCESS_INFO.get(pid)
        if key[0] is not None and cached is not None and cached[0] == key:
            started = cached[1]
        else:
            started = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "lstart="],
                capture_output=True, text=True, check=True, timeout=5,
            ).stdout.strip()
            if started and key[0] is not None:
                _PROCESS_INFO[pid] = (key, started)
        if not started:
            return None
        return Process(pid, str(path), started,
                       str(info.get("CFBundleShortVersionString", "unknown")),
                       bundle_id, stamp)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


_PROCESS_INFO: dict = {}            # pid -> ((kernel start time, executable, stamp), ps lstart text)
_PROC_PIDTBSDINFO = 3               # proc_pidinfo flavor: struct proc_bsdinfo (136 bytes)


def _start_time(lib, pid: int):
    """(seconds, microseconds) the kernel records as the process start, or None."""
    try:
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(136)
        if lib.proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, buffer, 136) < 136:
            return None
        return struct.unpack_from("<QQ", buffer.raw, 120)        # pbi_start_tvsec, pbi_start_tvusec
    except (AttributeError, OSError, struct.error):
        return None


def discover_processes() -> list[Process]:
    result = subprocess.run(["/bin/ps", "-axo", "pid=,comm="],
                            capture_output=True, text=True, check=True, timeout=5)
    processes = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2 or not re.search(r"/(Football Manager (26|27)|fm)$", parts[1]):
            continue
        process = process_info(int(parts[0]))
        if process:
            processes.append(process)
    return processes


def integer(value: int, low: int, high: int, name: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise BridgeError(f"{name} must be an integer from {low} to {high}.")


PERSON_TOKEN = re.compile(r'person:(\d{1,8})')


class PlayerRefs(dict):
    """player_ref -> binding. Besides the tokens the finder and roster tools hand out, a
    "person:<people-table index>" reference (the form the screen tools and fm_db_query results use)
    is accepted by every hand-built player tool: it is bound on first use by `resolve(index)` (the
    same checked binding the roster tools make) and kept like any other reference."""

    def __init__(self, resolve):
        super().__init__()
        self._resolve = resolve

    def get(self, key, default=None):
        hit = super().get(key)
        if hit is None and isinstance(key, str):
            m = PERSON_TOKEN.fullmatch(key)
            if m:
                hit = self._resolve(int(m.group(1)))
                if hit is not None:
                    self[key] = hit
        return default if hit is None else hit

    def __getitem__(self, key):
        hit = self.get(key)
        if hit is None:
            raise KeyError(key)
        return hit

    def __contains__(self, key):
        return self.get(key) is not None

    # A copy is a plain dict of the bindings: the resolver is a bound method of the Bridge, whose
    # locks cannot be copied, and callers copy this mapping to compare references before and after.
    def __deepcopy__(self, memo):
        import copy
        return {copy.deepcopy(k, memo): copy.deepcopy(v, memo) for k, v in self.items()}

    def __copy__(self):
        return dict(self)

    def copy(self):
        return dict(self)

    def __reduce__(self):
        return (dict, (dict(self),))


class Bridge:
    def __init__(self, helper: Path | None = None):
        self.helper = helper or Path(os.environ.get("FM_LIVE_HELPER", ROOT / "build/fm_live_helper"))
        self.process: Process | None = None
        self.session: str | None = None
        self.anchors: dict[str, dict] = {}
        self.cursors: dict[str, dict] = {}
        self.player_refs: dict[str, dict] = PlayerRefs(self._bind_person_index)
        self.player_cursors: dict[str, dict] = {}
        self.team_refs: dict[str, dict] = {}
        self.database_cursors: dict[str, dict] = {}
        self.club_refs: dict[str, dict] = {}
        self.staff_refs: dict[str, dict] = {}
        self.competition_refs: dict[str, dict] = {}
        self.stage_refs: dict[str, dict] = {}
        self.fixture_refs: dict[str, dict] = {}
        self.stadium_refs: dict[str, dict] = {}
        self.stadium_change_refs: dict[str, dict] = {}
        self.currency_refs: dict[str, dict] = {}
        self.city_refs: dict[str, dict] = {}
        self.geographic_refs: dict[str, dict] = {}
        self.plugin_identity: tuple | None = None
        self.world_identity: tuple | None = None
        self.lock = threading.RLock()
        self._reader = None

    def _run(self, command: str, process: Process, *args: str) -> dict:
        if not self.helper.is_file():
            raise BridgeError("Native reader missing. Run sh scripts/build_helper.sh.")
        try:
            result = subprocess.run(
                [str(self.helper), command, "--pid", str(process.pid), *args],
                capture_output=True, text=True, timeout=45, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BridgeError("Reader timed out after 45s. Check the Mac for Developer Tools Access authentication; no result was accepted.") from exc
        except OSError as exc:
            raise BridgeError(f"Cannot launch native reader: {exc}") from exc
        except UnicodeError as exc:
            raise BridgeError("Native reader returned invalid Unicode; no result accepted.") from exc
        try:
            data = json.loads(result.stdout)
        except ValueError as exc:
            raise BridgeError("Native reader did not return valid JSON.") from exc
        if not isinstance(data, dict):
            raise BridgeError("Native reader returned an invalid response.")
        if result.returncode or data.get("ok") is not True:
            raise BridgeError(f"Native reader failed: {data.get('error', result.stderr[:200])}")
        if data.get("pid") != process.pid or data.get("command") != command:
            raise BridgeError("Native response does not match the requested process/operation.")
        if process_info(process.pid) != process:
            self._clear()
            raise BridgeError("Game process changed during the read. Attach again.")
        return data

    def _clear(self) -> None:
        self.process = None
        self.session = None
        self._images = None
        self.anchors.clear()
        self.cursors.clear()
        self.player_refs.clear()
        self.player_cursors.clear()
        self.team_refs.clear()
        self.database_cursors.clear()
        self.club_refs.clear()
        self.staff_refs.clear()
        self.competition_refs.clear()
        self.stage_refs.clear()
        self.fixture_refs.clear()
        self.stadium_refs.clear()
        self.stadium_change_refs.clear()
        self.currency_refs.clear()
        self.city_refs.clear()
        self.geographic_refs.clear()
        self.plugin_identity = None
        self.world_identity = None

    def _current(self, session_id: str) -> Process:
        if not self.process or session_id != self.session:
            raise BridgeError("Unknown session. Call fm_attach first.")
        if process_info(self.process.pid) != self.process:
            self._clear()
            raise BridgeError("Game exited, restarted, or changed build. Attach again.")
        return self.process

    def status(self) -> dict:
        with self.lock:
            if self.process and process_info(self.process.pid) != self.process:
                self._clear()
            return {
                "server_version": __version__,
                "game_build": address_book.report(),
                "platform_supported": sys.platform == "darwin",
                "helper_exists": self.helper.is_file(),
                "processes": [asdict(p) for p in discover_processes()] if sys.platform == "darwin" else [],
                "session_id": self.session,
                "capabilities": {"process_attachment": True, "text_search": True,
                                 "anchor_readback": True, "decoded_players": True,
                                 "resident_current_player_statistics": True,
                                 "indexed_archived_player_statistics": True,
                                 "team_league_performance_comparison": True, "resident_league_goal_scorers": True,
                                 "decoded_clubs": True, "loaded_save": True, "current_game_date": True,
                                 "native_injury_status_projection": True, "managed_squad": True, "stored_personal_tactical_overrides": True, "managed_tactical_assignments": True, "managed_in_possession_positions": True, "managed_team_sheet": True, "managed_prepared_tactics": True, "player_club_links": True,
                                 "prepared_formation_ids": True, "prepared_team_instructions": True,
                                 "saved_career_catalog": True, "saved_club_search": True, "saved_club_squads": True, "saved_team_search": True, "saved_team_nation_context": True, "saved_competition_search": True, "saved_currency_search": True, "stored_player_assessments": True, "stored_joining_interest": True, "stored_player_bans": True, "managed_personal_shortlists": True, "managed_training_schedule": True, "prepared_base_roles": True, "prepared_formation_english_names": True,
                                 "loan_status": True, "club_squads": True,
                                 "virtual_players": True, "team_player_query": True,
                                 "roster_profile_availability": True, "stored_virtual_identity": True,
                                 "database_catalog": True, "save_player_search": True,
                                 "save_player_query": True, "save_club_search": True, "other_club_squads": True,
                                 "save_staff_search": True, "staff_contract_club": True,
                                 "competition_search": True, "stored_competition_identity": True,
                                 "competition_team_assignments": True, "competition_registrations": True,
                                 "competition_stages": True, "stored_league_standings": True,
                                 "resident_fixture_coverage": True, "fixture_query": True, "declared_fixture_rules": True, "stored_fixture_scores": True, "stored_fixture_kickoff_times": True, "fixture_stage_links": True, "stored_fixture_names": True, "stadium_query": True, "fixture_venues": True, "city_query": True, "stadium_links": True, "language_query": True, "local_region_query": True, "weather_profile_query": True, "stadium_change_query": True, "currency_query": True, "stored_currency_conversion": True,
                                 "club_staff": True, "stored_staff_attributes": True,
                                 "club_staff_query": True, "staff_jobs": True, "contract_dates": True, "weekly_contract_wages": True, "contract_cash_bonuses": True, "contract_terms": True, "loan_contracts": True, "contract_status": True, "player_profile": True, "personality_ratings": True, "club_finances": True, "current_transfer_budget": True, "transfer_fee_comparison": True, "remaining_wage_budget": True, "wage_budget_comparison": True, "weekly_wage_contributions": True, "live_transfer_offers": True, "live_transfer_offer_state_labels": False, "stored_player_health": True, "player_injury_records": True,
                                 "memory_writes": bool(getattr(self, 'write_module', False)),
                                 "stored_club_training_intensity_edit": bool(getattr(self, 'write_module', False))
                                                                         and (self.helper.parent / 'fm_training_editor').is_file()},
                "save_identity": "unverified",
                "limitations": [
                    "Text matches can be UI caches or static data; they do not establish a player record or loaded-save identity.",
                    "Call fm_get_save for fresh loaded-career verification and fm_get_managed_squad for the native managed-team roster.",
                    "Managed prepared tactics identify the stored primary trained tactic and both phase positions. Optional details include numeric formation IDs, stored mentality and selected team instructions. Current match assignment, official formation names, roles, familiarity and player assignments remain unverified.",
                    "Roster and player reads default to required rich profiles. Explicit profile_policy='available' preserves checked stored virtual identities when expanded profiles are absent or an otherwise typed generated cache belongs to a different PERSON; unavailable fields are null and identified separately from roster membership.",
                    "Reads are best-effort, not an atomic snapshot. Reattach after loading another save.",
                    "No FM26 field offsets are assumed valid for FM27.",
                    f"Player decoding requires the verified ARM64 game plugin for FM27 {players.VERSION}; other builds fail closed.",
                    "Verified fields: player names, birth date, 36 outfield attributes, loaded career metadata with the current simulation calendar date, club rosters including cached virtual players, optional contract clubs and loan status, and staff identity, stored ratings and native job titles. Optional contract dates include computed dynamic expiry; status and weekly main-contract wages in GBP are supported, with staff expiry and wage filtering. Optional player profiles include ability, potential, position ratings, goalkeeper ratings, five hidden ratings, foot strength and eight personality ratings, with squad filtering and sorting. Staff rating reads and queries also support personality. Save-wide player queries support inclusive attribute/profile bounds and birth-date ranges, with lossless continuation in native table order and explicit unknown fixed potential. Stored condition, sharpness, fatigue and named injury records are available with health filters. Club finances expose stored balance, total weekly wage budget and transfer budget, plus the native current transfer budget for the verified normal-career branch and an upfront-fee comparison. Unsupported adjustments stay unavailable; base records expose balance only. Stored main-contract terms and loan agreements, including recall and playing clause flags, have dedicated queries. Remaining wage room and weekly wage contributions are available. Competition queries enumerate stored identities, names and context, with geography/type/gender/extinction filters; runtime stages and stored league tables include overall/home/away statistics, point rules and team references. Broader competition rules and current activity are not decoded. Virtual condition/sharpness, recovery forecasts, clause activation, complete offer affordability, full archived history and complete future schedules remain unsupported. Resident fixture queries expose dates and calendar-day offsets from save.current_date, stored kickoff clocks without a verified timezone, scores and team/competition links.",
                ],
            }

    def attach(self, pid: int | None = None) -> dict:
        with self.lock:
            if pid is None:
                candidates = discover_processes()
                if len(candidates) != 1:
                    raise BridgeError(f"Found {len(candidates)} games. Use fm_status and select a PID explicitly.")
                process = candidates[0]
            else:
                integer(pid, 1, 2**31 - 1, "pid")
                process = process_info(pid)
                if process is None:
                    raise BridgeError("PID is not a supported Football Manager 26/27 application.")
            self._clear()
            native = self._run("probe", process)
            if native.get("attach_ok") is not True:
                raise BridgeError("Native reader did not confirm attachment.")
            self.process = process
            self.session = secrets.token_urlsafe(18)
            return {"session_id": self.session, "process": asdict(process),
                    "memory_access": "verified", "save_identity": "unverified",
                    "regions": native.get("regions"), "read_only": not getattr(self, 'write_module', False),
                    "attachment_performed_writes": False,
                    "editing_scope": ("The write module is loaded: fm_set_player_training_intensity can edit game memory; every other tool is read-only."
                                      if getattr(self, 'write_module', False) else "This reader is read-only: no tool edits game memory.")}

    def search(self, session_id: str, texts: list[str], max_mib: int = 256,
               max_matches: int = 20, cursor: str | None = None) -> dict:
        with self.lock:
            process = self._current(session_id)
            integer(max_mib, 1, 1024, "max_mib")
            integer(max_matches, 1, 100, "max_matches")
            if not isinstance(texts, list) or not 1 <= len(texts) <= 8:
                raise BridgeError("Supply between 1 and 8 search texts.")
            for value in texts:
                if not isinstance(value, str) or not 3 <= len(value) <= 128 or any(ord(c) < 32 for c in value):
                    raise BridgeError("Each text must contain 3–128 characters and no control characters.")
                try:
                    value.encode("utf-8")
                except UnicodeError as exc:
                    raise BridgeError("Search text must be valid Unicode.") from exc
            address = 0
            if cursor is not None and (not isinstance(cursor, str) or not cursor):
                raise BridgeError('Search cursor must be a nonempty string.')
            if cursor is not None:
                saved = self.cursors.get(cursor)
                if not saved or saved["texts"] != texts:
                    raise BridgeError("Cursor is invalid or belongs to a different search. Keep the same texts.")
                address = saved["address"]
            args = ["--private-only", "--writable-only", "--start-address", str(address),
                    "--max-bytes", str(max_mib * 1024 * 1024), "--max-matches", str(max_matches)]
            hex_labels = {}
            for value in dict.fromkeys(texts):
                args.extend(["--needle", value])
                if not value.isascii():
                    encoded = value.encode("utf-16le").hex()
                    hex_labels[encoded] = value
                    args.extend(["--hex-needle", encoded])
            native = self._run("scan-session", process, *args)
            if not isinstance(native.get("matches"), list) or native.get("stop_reason") not in {
                "byte_budget", "match_limit", "address_space_end"
            }:
                raise BridgeError("Native reader is incompatible. Rebuild with scripts/build_helper.sh.")
            # Bound retained state over a long MCP connection.
            if len(self.anchors) + len(native["matches"]) > 1000:
                self.anchors.clear()
            matches = []
            for raw in native["matches"]:
                match = dict(raw)
                match.pop("confidence", None)  # FM26's fixed score was not semantic evidence.
                if match["value"] in hex_labels:
                    match["value"] = hex_labels[match["value"]]
                    match["encoding"] = "utf-16le"
                anchor_id = secrets.token_urlsafe(12)
                match.update(anchor_id=anchor_id, evidence="text_match_only")
                self.anchors[anchor_id] = match
                matches.append(match)
            next_cursor = None
            if native["stop_reason"] == "byte_budget":
                next_address = int(native["next_address"], 16)
                if next_address <= address:
                    raise BridgeError("Native scan made no forward progress.")
                if len(self.cursors) >= 100:
                    self.cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.cursors[next_cursor] = {"address": next_address, "texts": list(texts)}
            return {"session_id": session_id, "observed_at": datetime.now(timezone.utc).isoformat(),
                    "matches": matches, "scan": native.get("scan"),
                    "stop_reason": native["stop_reason"], "next_cursor": next_cursor,
                    "coverage": "private writable memory only; bounded, non-atomic scan",
                    "absence_proven": False,
                    "note": "A match is research evidence, not a decoded entity. Match-limit results have no continuation; use a more specific text."}

    def read_anchor(self, session_id: str, anchor_id: str, before: int = 32, after: int = 96) -> dict:
        with self.lock:
            process = self._current(session_id)
            integer(before, 0, 256, "before")
            integer(after, 0, 512, "after")
            anchor = self.anchors.get(anchor_id)
            if not anchor:
                raise BridgeError("Unknown or expired anchor. Search again.")
            needle = anchor["value"].encode(anchor["encoding"])
            address = int(anchor["address"], 16)
            start = max(int(anchor["region"]["start"], 16), address - before)
            end = min(int(anchor["region"]["end"], 16), address + len(needle) + after)
            native = self._run("read-bytes", process, "--addr", str(start), "--read-len", str(end - start))
            try:
                data = bytes.fromhex(native["hex"])
            except (KeyError, TypeError, ValueError) as exc:
                raise BridgeError("Native reader returned invalid bytes.") from exc
            if len(data) != end - start:
                raise BridgeError("Incomplete memory read; no anchor result accepted.")
            offset = address - start
            if data[offset:offset + len(needle)] != needle:
                del self.anchors[anchor_id]
                raise BridgeError("Anchor changed since search. Search again; cached address was rejected.")
            return {"session_id": session_id, "anchor_id": anchor_id, "address": hex(start),
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "anchor_still_matches": True, "value": anchor["value"],
                    "encoding": anchor["encoding"], "anchor_offset": offset,
                    "hex": data.hex(), "evidence": "verified_text_bytes_only"}

    def _read_memory(self, process: Process, address: int, length: int) -> bytes:
        if not 0 < address < 2**64 - length or not 1 <= length <= 16384:
            raise BridgeError("Invalid bounded memory read.")
        if self._reader is not None:
            if self._reader.pid != process.pid:
                raise BridgeError('Native read stream belongs to another process.')
            try:
                return self._reader.read(address, length)
            except ReaderError as exc:
                raise BridgeError(str(exc)) from exc
        native = self._run("read-bytes", process, "--addr", str(address), "--read-len", str(length))
        try:
            data = bytes.fromhex(native["hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BridgeError("Native reader returned invalid bytes.") from exc
        if len(data) != length:
            raise BridgeError("Incomplete player read; no result accepted.")
        return data

    @contextmanager
    def _read_scope(self, session_id, *, final_verify=None):
        """Hold the bridge lock externally; close the task port on every exit."""
        process = self._current(session_id)
        if self._reader is not None:
            raise BridgeError('Nested native read scope rejected.')
        reader = self._reader = ReadStream(self.helper, process.pid)
        try:
            yield
            self._current(session_id)
            if final_verify is not None:
                final_verify()
        finally:
            self._reader = None
            reader.close()

    def _player_layout(self, process: Process) -> tuple[int, int, int]:
        if process.bundle_id != "com.SportsInteractive.FootballManager27":
            raise BridgeError(f"Unsupported player layout. Requires FM27 {players.VERSION} with the verified ARM64 plugin.")
        if process.version != players.VERSION:
            # players.VERSION is the build the address book loaded (the pinned one, or the build
            # whose address map address_book.py applied at import)
            raise BridgeError(address_book.refusal(process.version))
        try:
            # The loaded plugin image does not change while the process lives: the helper is
            # asked once per process (a subprocess each time cost 50-100 ms under load); the
            # path, file identity and runtime layout below are still checked on every call.
            cached = getattr(self, "_images", None)
            if cached is not None and cached[0] == process:
                images = cached[1]
            else:
                images = self._run("images", process)["images"]
                self._images = (process, images)
            if len(images) != 1:
                raise ValueError("Expected one loaded game plugin")
            path = Path(images[0]["path"]).resolve()
            contents = Path(process.executable).resolve().parent.parent
            if not path.is_relative_to(contents):
                raise ValueError("Loaded game plugin is outside the attached application")
            stat = path.stat()
            stamp = (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if self.plugin_identity is None or self.plugin_identity[0] != stamp:
                try:
                    self.plugin_identity = (stamp, players.disk_uuid(path))
                except ValueError as exc:
                    if "fingerprint" in str(exc):
                        raise BridgeError(address_book.refusal(process.version, address_book.plugin_sha256(path))) from exc
                    raise
            return players.verify_runtime(lambda a, n: self._read_memory(process, a, n),
                                          int(images[0]["address"], 16), self.plugin_identity[1])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            self._images = None
            self.player_refs.clear()
            self.player_cursors.clear()
            self.team_refs.clear()
            self.database_cursors.clear()
            self.club_refs.clear()
            self.staff_refs.clear()
            self.competition_refs.clear()
            self.stage_refs.clear()
            self.fixture_refs.clear()
            self.stadium_refs.clear()
            self.stadium_change_refs.clear()
            self.currency_refs.clear()
            self.city_refs.clear()
            self.geographic_refs.clear()
            self.plugin_identity = None
            raise BridgeError(f"Player layout verification failed: {exc}") from exc

    def _decode_player(self, process: Process, address: int, tables: tuple) -> tuple[dict, tuple]:
        try:
            return players.decode(lambda a, n: self._read_memory(process, a, n), address, tables)
        except (ValueError, IndexError) as exc:
            raise BridgeError(f"Player record rejected: {exc}") from exc

    def _world_state(self, process: Process, tables: tuple):
        snapshot = world.ReadSet(lambda a, n: self._read_memory(process, a, n))
        try:
            record, identity = world.loaded(snapshot, tables[0] - players.RVA[0])
            snapshot.verify()
        except (ValueError, IndexError) as exc:
            raise BridgeError(f"Loaded game record rejected: {exc}") from exc
        if self.world_identity is not None and identity != self.world_identity:
            self._clear()
            raise BridgeError("Loaded game identity changed. Attach again; previous references were discarded.")
        self.world_identity = identity
        return snapshot, record, identity

    @staticmethod
    def _public_save(record: dict) -> dict:
        return {**record, "coaches": [{"name": c["name"], "club": c["club"]} for c in record["coaches"]]}

    def get_save(self, session_id: str) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            _, record, _ = self._world_state(process, tables)
            self._current(session_id)
            return {"session_id": session_id, "observed_at": datetime.now(timezone.utc).isoformat(),
                    "save": self._public_save(record), "evidence": "native_game_save_system_roots_and_simulation_date_anchor",
                    "limitations": "current_date is the native simulation calendar date; last_saved_date is separate. No current clock time or timezone is established. Non-atomic reads with byte rechecks; reattach after loading a save. Only employed active human managers are supported."}

    def get_next_match_squad(self, session_id: str, coach_name: str | None = None,
                             window_days: int = 35, position_minimum: int = 15,
                             max_fixture_pages: int = 20) -> dict:
        from . import next_match_squad
        integer(window_days, 1, 366, 'window_days')
        integer(position_minimum, 1, 20, 'position_minimum')
        integer(max_fixture_pages, 1, 50, 'max_fixture_pages')
        with self.lock, self._read_scope(session_id):
            try:
                return next_match_squad.collect(self, session_id, coach_name, window_days,
                                                position_minimum, max_fixture_pages)
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Next-match squad rejected; no partial observation returned: {exc}') from exc

    @contextmanager
    def _roster_publication_scope(self, session_id, reference_checks):
        """Seal only core roster reads; callers hold the lock and publish after close."""
        def seal():
            # _read_scope's hidden post-yield callback has already run. Every
            # remaining callback/cache check precedes both complete byte fences.
            if self._current(session_id) != process:
                raise ValueError('Roster process lifetime changed')
            after_tables = self._player_layout(process)
            if after_tables != tables or self.plugin_identity != plugin:
                raise ValueError('Roster loaded plugin/build changed')
            after_read, after_record, after_identity = self._world_state(process, after_tables)
            if (after_record != saved_record or record != saved_record
                    or after_identity != identity or self.world_identity != identity):
                raise ValueError('Roster loaded save/date context changed')
            if players.verify_runtime(after_read, base, plugin[1]) != tables:
                raise ValueError('Roster final runtime layout binding differs')
            if self._current(session_id) != process:
                raise ValueError('Roster final process lifetime changed')
            if (self.session != session_id or self.process != process
                    or self.plugin_identity != plugin or self.world_identity != identity
                    or any(type(getattr(self, name)) is not dict
                           or getattr(self, name).get(ref) != binding
                           for name, ref, binding in reference_checks)):
                raise ValueError('Roster final context/reference binding changed')
            snapshot.verify()
            after_read.verify()

        try:
            with self._read_scope(session_id, final_verify=seal):
                process = self._current(session_id)
                tables = self._player_layout(process)
                plugin = deepcopy(self.plugin_identity)
                snapshot, loaded, identity = self._world_state(process, tables)
                record, saved_record, identity = deepcopy(loaded), deepcopy(loaded), deepcopy(identity)
                if self.world_identity != identity:
                    raise ValueError('Roster initial world binding differs')
                base = tables[0] - players.RVA[0]
                if players.verify_runtime(snapshot, base, plugin[1]) != tables:
                    raise ValueError('Roster runtime layout binding differs')
                yield snapshot, record, tables
        except (ValueError, IndexError) as exc:
            raise BridgeError(f'Roster publication rejected; no partial roster returned: {exc}') from exc

    def get_managed_squad(self, session_id: str, coach_name: str | None = None,
                          include_clubs: bool = False, include_profile: bool = False, include_health: bool = False, profile_policy: str = "required") -> dict:
        self._profile_policy(profile_policy)
        if type(include_health) is not bool:
            raise BridgeError('include_health must be a boolean.')
        if type(include_profile) is not bool:
            raise BridgeError('include_profile must be a boolean.')
        if type(include_clubs) is not bool:
            raise BridgeError("include_clubs must be a boolean.")
        with self.lock:
            reference_checks = []
            with self._roster_publication_scope(session_id, reference_checks) as (snapshot, record, tables):
                coach = self._select_coach(record, coach_name)
                pending = []
                team_cache = {}
                try:
                    context = None
                    if profile_policy == 'available':
                        _, context = self._roster_team(snapshot, tables[0] - players.RVA[0], coach['team_address'])
                    addresses = world.vector(snapshot, coach["team_address"] + 0x38, 256)
                    for index, address in enumerate(addresses):
                        player, identity = self._roster_player(snapshot, address, tables, include_clubs, team_cache,
                                                              include_profile, include_health, profile_policy)
                        if context is not None:
                            self._roster_available_context(snapshot, address, tables, player, identity, context, index)
                        pending.append((address, player, identity))
                    prepared = [self._player_binding(address, player, identity, tables, profile_policy)
                                for address, player, identity in pending]
                    accounting = self._roster_accounting([player for _, player, _ in pending], profile_policy)
                    snapshot.verify()
                except (ValueError, IndexError, BridgeError) as exc:
                    raise BridgeError(f"Managed squad rejected; no partial roster returned: {exc}") from exc
                public_save = self._public_save(record)
            result, published = [], {}
            for (address, player, identity), binding in zip(pending, prepared):
                ref = secrets.token_urlsafe(12)
                published[ref] = binding
                result.append({**player, "player_ref": ref})
            if len(self.player_refs) + len(pending) > 1000:
                self.player_refs.clear()
            self.player_refs.update(published)
            return {"session_id": session_id, "observed_at": datetime.now(timezone.utc).isoformat(),
                    "save": public_save, "coach": coach["name"], "club": coach["club"],
                    "players": result, "count": len(result), "complete_native_roster": True,
                    **accounting,
                    "evidence": "game_root_to_active_manager_to_club_team_roster",
                    "limitations": "The native managed-team roster can include loaned-out players and differs from UI filters or youth call-ups. This is not the whole club or a match-eligibility list. Unsupported records fail the whole query. Non-atomic reads with byte rechecks." + (
                        ' Available policy preserves checked virtual identities with explicit unavailable expanded fields; roster context does not establish contract/current club or loan status.'
                        if profile_policy == 'available' else '')}

    @staticmethod
    def _validate_player_ref_list(player_refs):
        if (not isinstance(player_refs, list) or not 1 <= len(player_refs) <= 100
                or any(not isinstance(ref, str) or not ref for ref in player_refs)):
            raise BridgeError('Supply 1 through 100 nonempty player references.')

    def _bound_subjects(self, session_id, read, base, tables, people, player_refs):
        subjects = {}
        for ref in dict.fromkeys(player_refs):
            binding = self.player_refs.get(ref)
            if binding is None:
                raise ValueError('Unknown or expired player reference.')
            try:
                subjects[ref] = assessment_people.bound_player(read, base, tables, people, binding)
            except assessment_people.StalePlayerReference:
                read.verify()
                self._current(session_id)
                self.player_refs.pop(ref, None)
                raise
        return subjects

    def get_player_concern_history(self, session_id: str, player_refs: list[str],
                                   coach_name: str | None = None, *, include_templates: bool = False,
                                   include_promises: bool = False) -> dict:
        from .live_player_concern_history import get_player_concern_history
        return get_player_concern_history(self, session_id, player_refs, coach_name,
                                          include_templates=include_templates,
                                          include_promises=include_promises)

    def get_player_injury_status(self, session_id: str, player_refs: list[str] | None = None,
                                 coach_name: str | None = None) -> dict:
        """Inspect current picked slots, or an explicit batch, in one checked read."""
        if player_refs is not None:
            self._validate_player_ref_list(player_refs)
            if coach_name is not None:
                raise BridgeError('coach_name applies only when player_refs are omitted.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            read, save, _ = self._world_state(process, tables)
            pending = []
            try:
                player_injury_status.verify_native(read, base)
                current_raw = read(base + world.CURRENT_DATE, 4)
                sentinel_raw = read(base + player_injury_status.SENTINEL_DATE, 4)
                if player_injury_status.calendar(current_raw)[0].isoformat() != save['current_date']:
                    raise ValueError('Injury-status date differs from the checked save date')
                people = database.table(read, base, 'people')
                selection = None
                requested = []
                if player_refs is None:
                    coach = self._select_coach(save, coach_name)
                    sheet = live_team_sheet_source.inspect(read, base, coach)
                    selection = {
                        'coach': coach['name'], 'club': coach['club'], 'team': sheet['team'],
                        'source_state': sheet['source_state'],
                        'unavailable_reason': sheet['unavailable_reason'],
                        'role_boundary_state': sheet['role_boundary_state'],
                        'bench_end': sheet.get('bench_end'),
                        'bench_boundary_source': sheet.get('bench_boundary_source'),
                        'bench_boundary_unavailable_reason': sheet.get('bench_boundary_unavailable_reason'),
                        'bench_fixture': sheet.get('bench_fixture'),
                        'slots': None if sheet['slots'] is None else [{
                            'slot_index': slot['slot_index'], 'category': slot['category'],
                            'state': slot['state'],
                            'person_index': None if slot['person'] is None else slot['person']['database_index'],
                        } for slot in sheet['slots']],
                    }
                    if live_team_sheet_source.bench_known(sheet):
                        identities = {}
                        for slot in sheet['slots']:
                            if slot['category'] not in ('starting_position', 'bench') or slot['person'] is None:
                                continue
                            index = slot['person']['database_index']
                            if index not in identities:
                                person_address = world.pointer(read, people['start'] + index * 8)
                                primary, _, identity, _, _ = assessment_people._person(
                                    read, base, people, person_address)
                                decoded, token = self._roster_player(
                                    read, primary, tables, False, {}, profile_policy='available')
                                if decoded['native_identity'] != identity['native_identity']:
                                    raise ValueError('Picked injury-status identity changed')
                                identity = {**identity, 'display_name': decoded['display_name']}
                                binding = self._player_binding(primary, decoded, token, tables, 'available')
                                identities[index] = (primary, identity, binding)
                            primary, identity, binding = identities[index]
                            requested.append((None, primary, identity, slot['slot_index'], slot['category']))
                            pending.append(binding)
                else:
                    regular = []
                    virtual_subjects = {}
                    for reference in dict.fromkeys(player_refs):
                        saved = self.player_refs.get(reference)
                        if saved is None:
                            raise ValueError('Unknown or expired player reference')
                        if saved.get('record_kind') != 'virtual':
                            regular.append(reference)
                            continue
                        if saved.get('tables') != tables:
                            raise ValueError('Virtual injury-status reference layout changed')
                        core = virtual_identity.inspect(read, saved['address'], tables)
                        if saved.get('binding_kind') == virtual_identity.BINDING_KIND:
                            if (saved.get('database_index') != core['native_identity']['database_index']
                                    or saved.get('person_offset') != 0x20):
                                raise ValueError('Stored virtual injury-status reference membership changed')
                            token = core['identity']
                            name = None
                        elif saved.get('binding_kind') is None:
                            decoded, token = virtual.decode(read, saved['address'], tables)
                            name = decoded['display_name']
                        else:
                            raise ValueError('Unsupported virtual injury-status reference kind')
                        if token != saved.get('identity'):
                            read.verify()
                            self._current(session_id)
                            self.player_refs.pop(reference, None)
                            raise ValueError('Virtual injury-status reference identity changed')
                        virtual_subjects[reference] = (saved['address'] + 0x20, {
                            'record_kind': 'virtual', 'display_name': name,
                            'native_identity': core['native_identity'],
                        })
                    subjects = self._bound_subjects(session_id, read, base, tables, people, regular)
                    subjects.update(virtual_subjects)
                    for reference in player_refs:
                        _, identity = subjects[reference]
                        requested.append((reference, self.player_refs[reference]['address'], identity, None, None))
                projected = {}
                rows = []
                for reference, primary, identity, slot, category in requested:
                    if primary not in projected:
                        projected[primary] = player_injury_status.project(
                            read, base, primary, identity['record_kind'], current_raw, sentinel_raw)
                    rows.append({
                        'player_ref': reference, 'person': identity,
                        'slot_index': slot, 'selection_category': category,
                        'injury_status': projected[primary],
                    })
                complete_selection = player_refs is None and live_team_sheet_source.bench_known(selection)
                reply = {
                    'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'as_of_date': save['current_date'],
                    'scope': 'current_picked_XI_and_bench' if player_refs is None else 'explicit_player_references',
                    'selection': selection, 'complete_selected_person_coverage': complete_selection,
                    'state': ('unavailable' if player_refs is None and not complete_selection else
                              'partial' if any(row['injury_status']['flagged'] is None for row in rows)
                              else 'available'),
                    'players': rows, 'count': len(rows), 'unique_person_count': len(projected),
                    'count_scope': 'nonnull_picked_slots' if player_refs is None else 'requested_reference_rows',
                    'unavailable_reason': (None if player_refs is not None or complete_selection else
                                           selection['unavailable_reason'] or 'selection_boundary_unresolved'),
                    'flagged_count': sum(row['injury_status']['flagged'] is True for row in rows),
                    'checked_negative_count': sum(row['injury_status']['flagged'] is False for row in rows),
                    'unsupported_count': sum(row['injury_status']['flagged'] is None for row in rows),
                    'complete_status_coverage': (player_refs is not None or complete_selection)
                                                and all(row['injury_status']['state'] == 'checked' for row in rows),
                    'source': 'bounded_reconstruction_of_native_actual_player_injury_status',
                    'status_flags_object_read': False, 'native_getter_or_producer_executed': False,
                    'fixture_clearance': 'not_assessed',
                    'limitations': 'Current-date injury-status branch only, reconstructed from checked stored inputs. '
                        'Without player_refs the people are the XI and bench of the current editable selection, '
                        'not a submitted match squad; selection.bench_boundary_source says where the bench ends. '
                        'English Inj/Injured labels do not establish foreground rendering or display priority. '
                        'Checked false is a negative on this getter, not medical or future-match clearance. '
                        'Stored injury records remain separate; unsupported branches have flagged null. '
                        'Return estimates use the separate injury-return tool. Non-atomic byte, date, '
                        'selection ownership, canonical identity and process rechecks; no game functions executed.',
                }
                if len(json.dumps(reply, ensure_ascii=True).encode()) + 20 * len(pending) > 2 * 1024 * 1024:
                    raise ValueError('Injury-status response exceeds budget')
                read.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'Injury-status query rejected; no partial read returned: {exc}') from exc
            if pending:
                if len(self.player_refs) + len(pending) > 1000:
                    self.player_refs.clear()
                references = {}
                for row, binding in zip(rows, pending, strict=True):
                    key = binding['address']
                    if key not in references:
                        references[key] = secrets.token_urlsafe(12)
                        self.player_refs[references[key]] = binding
                    row['player_ref'] = references[key]
            return reply

    def get_player_injury_return_estimates(self, session_id: str, player_refs: list[str]) -> dict:
        """Reconstruct audited current-club estimate inputs without report creation."""
        self._validate_player_ref_list(player_refs)
        if len(player_refs) > 32:
            raise BridgeError('Supply 1 through 32 player references for injury estimates.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            read, save, _ = self._world_state(process, tables)
            try:
                people = database.table(read, base, 'people')
                subjects = self._bound_subjects(session_id, read, base, tables, people, player_refs)
                player_injury_return.verify_native(read, base)
                estimates, club_cache = {}, {}
                for ref, (person, identity) in subjects.items():
                    if person not in estimates:
                        estimates[person] = player_injury_return.project(
                            read, base, self.player_refs[ref]['address'], identity['record_kind'],
                            current_date=save['current_date'], club_cache=club_cache)
                rows = [{'player_ref': ref, **subjects[ref][1],
                         'injury_return': estimates[subjects[ref][0]]} for ref in player_refs]
                reply = {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                         'save': self._public_save(save), 'players': rows,
                         'scope': dict(player_injury_return.SCOPE),
                         'limitations': 'Reconstructed native injury-property estimates using current club-selected medical inputs; '
                                        'not a captured resident report, verified display wording, medical clearance or eligibility. '
                                        'Converted dates add remaining calendar days to the current date. '
                                        'Only audited branches are supported; each other injury retains an explicit reason. '
                                        'Independent injury windows are not combined into an overall recovery date.'}
                if len(json.dumps(reply, ensure_ascii=True).encode('ascii')) > 2 * 1024 * 1024:
                    raise ValueError('Injury estimate response exceeds budget; request fewer players')
                read.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'Injury estimate query rejected; no partial read returned: {exc}') from exc
            return reply

    def get_current_player_cup_history(self, session_id, competition_ref, player_refs,
                                       fixture_ref=None):
        from . import current_cup_history, teams
        self._validate_player_ref_list(player_refs)
        if len(player_refs) > 32:
            raise BridgeError('Supply at most32 cup-history player references.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            read, save, _ = self._world_state(process, tables)
            base = tables[0] - players.RVA[0]
            comp = self.competition_refs.get(competition_ref) if isinstance(competition_ref, str) else None
            if comp is None:
                raise BridgeError('Unknown or expired competition reference.')
            try:
                people = database.table(read, base, 'people')
                subjects = self._bound_subjects(session_id, read, base, tables, people, player_refs)
                indices = {identity['native_identity']['database_index'] for person, identity in subjects.values()
                           if identity['record_kind'] == 'actual'}
                fixture = None
                fixture_teams = None
                if fixture_ref is None:
                    coverage, histories = current_cup_history.collect_current(read, base, comp, indices)
                else:
                    saved = self.fixture_refs.get(fixture_ref) if isinstance(fixture_ref, str) else None
                    if saved is None or saved['tables'] != tables:
                        raise ValueError('Unknown, expired or mismatched fixture reference')
                    _, years, inventory = fixtures.catalog(read, base)
                    if saved['catalog_identity'] != inventory:
                        raise ValueError('Resident fixture inventory changed')
                    entries, route = fixtures.bucket(read, years[saved['year']], saved['day'], saved['group'])
                    if (route != saved['route'] or saved['slot'] >= len(entries)
                            or entries[saved['slot']] != saved['address']):
                        raise ValueError('Fixture bucket membership changed')
                    decoded = fixtures.record(read, base, saved['address'], saved['year'], saved['day'], {})
                    if decoded['identity'] != saved['identity'] or decoded['competition_address'] != comp['address']:
                        raise ValueError('Fixture identity or competition disagrees')
                    detail, _, stage = fixtures.detail(read, base, saved['address'], saved['year'], saved['day'], decoded, {}, True)
                    fixture = {key: detail.get(key) for key in ('date', 'record_kind', 'home_team', 'away_team', 'competition')}
                    fixture_teams = decoded['teams']
                    coverage, histories = current_cup_history.collect(read, base, comp,
                        saved['address'], decoded, stage, indices)
                output = []
                for ref in player_refs:
                    person, identity = subjects[ref]
                    history = None if histories is None else histories.get(identity['native_identity']['database_index'])
                    current_team = None
                    condition = None
                    condition_state = 'fixture_not_requested'
                    if identity['record_kind'] != 'actual':
                        history = None
                        condition_state = 'unsupported_player_kind'
                    elif history is not None:
                        primary = self.player_refs[ref]['address']
                        pointer = players.u64(read(primary + 0x128, 8))
                        if pointer:
                            team_index = int.from_bytes(read(pointer + 8, 4), 'little')
                            current_team, binding = teams.by_index(read, base, team_index)
                            if binding['address'] != pointer:
                                raise ValueError('Current player TEAM disagrees with canonical table')
                            if fixture_ref is not None:
                                if pointer not in fixture_teams:
                                    condition_state = 'current_team_not_fixture_participant'
                                else:
                                    projected = current_cup_history.condition(history, team_index,
                                        coverage['phase']['rule_flags'])
                                    condition = projected['native_other_team_cup_history_condition']
                                    condition_state = projected['native_condition_reason']
                        elif fixture_ref is not None:
                            condition_state = 'current_team_absent'
                        history = {key: value for key, value in history.items()
                                   if not key.startswith('_') and key != 'native_other_team_cup_history_condition'}
                    elif fixture_ref is not None:
                        condition_state = 'source_unavailable'
                    output.append({'player_ref': ref, **identity, 'current_team': current_team,
                        'history': history, 'current_source_fixture_flag1_condition': condition,
                        'condition_state': condition_state})
                read.verify()
                self._current(session_id)
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Current cup history rejected: {exc}') from exc
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'source_date': save['current_date'],
                    'coverage': coverage, 'fixture_rule_context': fixture, 'players': output,
                    'fixture_eligibility': 'not_evaluated', 'historical_kickoff_verdict': 'not_evaluated',
                    'limitations': 'Current resident PERSON aggregate, not complete match history. '
                        'Counter is unsigned byte and can wrap; TEAM is last associated and may be overwritten. '
                        'Counter is not appearances for that TEAM. Absent row does not prove no past appearance. '
                        'Optional fixture compares CURRENT source to retained flag1 rule context; '
                        'a past fixture does not reconstruct kickoff state. Other cup restrictions, '
                        'registration, loans, bans and overall eligibility remain unknown.'}

    def get_player_bans(self, session_id: str, player_refs: list[str],
                        fixture_ref: str | None = None) -> dict:
        self._validate_player_ref_list(player_refs)
        if fixture_ref is not None and (not isinstance(fixture_ref, str) or not fixture_ref or len(fixture_ref) > 256):
            raise BridgeError('fixture_ref must be a nonempty fixture reference or null.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            read, save, _ = self._world_state(process, tables)
            try:
                people = database.table(read, base, 'people')
                subjects = self._bound_subjects(session_id, read, base, tables, people, player_refs)
                fixture_context = fixture_binding = None
                if fixture_ref is not None:
                    saved = self.fixture_refs.get(fixture_ref)
                    if saved is None or saved['tables'] != tables:
                        raise ValueError('Unknown, expired or mismatched fixture reference')
                    _, years, inventory = fixtures.catalog(read, base)
                    if saved['catalog_identity'] != inventory:
                        raise ValueError('Resident fixture inventory changed')
                    entries, route = fixtures.bucket(read, years[saved['year']], saved['day'], saved['group'])
                    if (route != saved['route'] or saved['slot'] >= len(entries)
                            or entries[saved['slot']] != saved['address']):
                        raise ValueError('Fixture bucket membership changed')
                    decoded = fixtures.record(read, base, saved['address'], saved['year'], saved['day'], {})
                    if decoded['identity'] != saved['identity']:
                        raise ValueError('Fixture identity changed')
                    fixture_context, fixture_binding = player_fixture_suspensions.context(
                        read, base, saved['address'], decoded, save['current_date'])
                    fixture_context['fixture_ref'] = fixture_ref
                    fixture_context['as_of_date'] = save['current_date']
                player_ban_source.verify_native(read, base)
                bans = {}
                for ref, (person, identity) in subjects.items():
                    if person not in bans:
                        primary = self.player_refs[ref]['address']
                        bans[person] = player_ban_source.project(read, primary, identity['record_kind'])
                        player_ban_source.resolve_competition_scopes(read, base, bans[person])
                        if fixture_ref is not None:
                            bans[person]['fixture_suspension'] = player_fixture_suspensions.project(
                                read, base, primary, identity['record_kind'], fixture_binding)
                rows = [{'player_ref': ref, **subjects[ref][1], **bans[subjects[ref][0]]}
                        for ref in player_refs]
                read.verify()
                self._current(session_id)
            except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
                raise BridgeError(f'Stored player ban query rejected: {exc}') from exc
            result = {
                'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': self._public_save(save), 'players': rows, 'eligibility_state': 'not_evaluated',
                'evidence': 'canonical_player_to_stored_secondary_ban_list',
                'limitations': 'Reads stored personal ban records for regular players. A missing secondary '
                               'record has unknown contents. Combined player/staff sources are unsupported. '
                               'English main text is available for supported international record kinds. '
                               'Kind1 scope is a canonical stored competition; stored match balance does not establish activation. '
                               'Fixture eligibility requires separate competition and team checks.',
            }
            if fixture_ref is not None:
                result.update(fixture_context=fixture_context,
                              fixture_suspension_scope=player_fixture_suspensions.SCOPE)
            return result

    def get_player_assessments(self, session_id: str, player_refs: list[str],
                               coach_name: str | None = None, source_offset: int = 0,
                               source_limit: int = 4096, include_joining_interest: bool = False) -> dict:
        if type(include_joining_interest) is not bool:
            raise BridgeError('include_joining_interest must be a boolean.')
        self._validate_player_ref_list(player_refs)
        if type(source_offset) is not int or source_offset < 0:
            raise BridgeError('source_offset must be a nonnegative integer.')
        if type(source_limit) is not int or not 1 <= source_limit <= 4096:
            raise BridgeError('source_limit must be an integer from 1 through 4096.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            read, save, _ = self._world_state(process, tables)
            coach = self._select_coach(save, coach_name)
            try:
                people = database.table(read, base, 'people')
                subjects = self._bound_subjects(session_id, read, base, tables, people, player_refs)
                matches = {address: [] for address, _ in subjects.values()}
                source, rows = assessment_source.project(
                    read, base, coach, set(matches), source_offset, source_limit, include_joining_interest)
                assessors = {}
                for index, subject, person, details in rows:
                    if person not in assessors:
                        assessors[person] = assessment_people.assessor(read, base, people, person)
                    matches[subject].append({'source_index': index, 'assessor': assessors[person], **details})
                read.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'Stored player assessment query rejected: {exc}') from exc
            result = []
            for ref in player_refs:
                address, identity = subjects[ref]
                result.append({'player_ref': ref, **identity, 'matches': matches[address]})
            return {
                'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': self._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                'source': source, 'players': result, 'completed_scout_report_status': 'unproved',
                'evidence': 'managed_team_context_to_stored_assessed_person_and_assessor',
                'limitations': 'Matches cover the examined slots in the managed team context. '
                               'The source includes coaching assessments. Dates describe record population. '
                               'Completed scout reports and grades remain unknown. Each page is a separate '
                               'non-atomic read with identity and consumed-byte rechecks.',
            }

    def get_managed_shortlists(self, session_id: str, coach_name: str | None = None,
                              list_index: int | None = None, offset: int = 0, limit: int = 50) -> dict:
        if list_index is not None and (type(list_index) is not int or list_index < 0):
            raise BridgeError('list_index must be a nonnegative native list index.')
        if type(offset) is not int or offset < 0:
            raise BridgeError('offset must be a nonnegative integer.')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise BridgeError('limit must be an integer from 1 through 100.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            coach = self._select_coach(save, coach_name)
            try:
                summary, selected, total = shortlist_source.inspect(snapshot, base, coach, list_index)
                page = [] if selected is None else shortlist_members.page(
                    snapshot, base, tables, selected, total, offset, limit)
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'Managed shortlist rejected: {exc}') from exc

            entries = []
            bindings = {}
            for row, binding in page:
                ref = None
                if binding is not None:
                    ref = secrets.token_urlsafe(12)
                    bindings[ref] = binding
                entries.append({**row, 'player_ref': ref})
            if len(self.player_refs) + len(bindings) > 1000:
                self.player_refs.clear()
            self.player_refs.update(bindings)
            end = offset + len(entries)
            return {
                'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': self._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                **summary, 'entries': entries, 'total_entries': total,
                'offset': offset, 'limit': limit, 'next_offset': end if total is not None and end < total else None,
                'report_availability': 'unavailable_unproved_report_source',
                'evidence': 'managed_human_personal_list_to_stored_canonical_person',
                'limitations': 'Entries reflect retained personal shortlist membership at the time of the read. '
                               'Activity, expiry and completed scout reports remain unknown. '
                               'Each page is a separate non-atomic read with identity and byte rechecks.',
            }

    def get_managed_training(self, session_id: str, coach_name: str | None = None,
                             start_date: str | None = None, day_count: int = 7) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            coach = self._select_coach(save, coach_name)
            try:
                dates = training_calendar.window(start_date, day_count, save['current_date'])
                team, reason, weeks = training_source.inspect(snapshot, base, coach)
                verified_resource = False
                if weeks:
                    training_calendar.verify_native(snapshot, base)
                    training_sessions.verify_native(snapshot, base)
                    verified_resource = training_sessions.resource_matches(process.executable)

                def label(slot_index, code):
                    return training_sessions.label(slot_index, code, verified_resource)

                days = training_calendar.decode(snapshot, weeks, dates, label)
                if weeks and training_sessions.resource_matches(process.executable) != verified_resource:
                    raise ValueError('Training session definition resource changed during the read')
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'Managed training rejected: {exc}') from exc
            native_type = team['native_type_code']
            return {
                'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': self._public_save(save), 'coach': coach['name'], 'club': coach['club'], 'team': team,
                'team_type': {'native_code': native_type, 'name': teams.EDITOR_TYPE_NAMES.get(native_type),
                              'source': 'build_editor_team_type_enum'},
                'source_state': 'available' if reason is None else 'unavailable',
                'unavailable_reason': reason,
                'window': {'start_date': dates[0].isoformat(), 'end_date': dates[-1].isoformat(),
                           'day_count': len(dates)},
                'complete_stored_window': all(day['state'] == 'stored_assigned' for day in days),
                'days': days, 'evidence': 'managed_team_to_resident_assigned_training_weeks',
                'limitations': 'Stored team schedule and native slot order. Individual attendance, '
                               'completion and session times are unknown. Missing weeks remain unavailable. '
                               'English names come from build-verified training definitions. '
                               'Reads are non-atomic with consumed-byte and process rechecks.',
            }

    def get_managed_tactical_assignments(self, session_id: str, coach_name: str | None = None,
                                        phase: str = 'both', include_personal_overrides: bool = False) -> dict:
        """Read checked working player assignments with the native per-creator phase map."""
        if type(phase) is not str or phase not in ('both', 'in_possession', 'out_of_possession'):
            raise BridgeError('phase must be both, in_possession or out_of_possession.')
        if type(include_personal_overrides) is not bool:
            raise BridgeError('include_personal_overrides must be a boolean.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            coach = self._select_coach(save, coach_name)
            try:
                if include_personal_overrides:
                    assignments = live_tactical_assignments_source.inspect(
                        snapshot, base, coach, phase, include_personal_overrides=True)
                else:
                    assignments = live_tactical_assignments_source.inspect(snapshot, base, coach, phase)
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'Tactical assignments rejected; no partial read returned: {exc}') from exc
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                    **assignments,
                    'evidence': 'owned_working_edit_session_native_phase_specific_player_pairings',
                    'limitations': 'Stored working tactical assignments. In-possession uses the selection slot; '
                        "out-of-possession uses the same creator's stored remap with the native FF fallback. "
                        'Repeated targets are preserved and reported, without assuming a permutation. '
                        'Unsupported map bytes stop the affected pairing only. Position and base-role labels '
                        'use verified compiled English branches. Foreground screen, match submission, '
                        'eligibility and effective player overrides are not established. Reads are '
                        'non-atomic with consumed-byte and process rechecks.'}

    def get_managed_in_possession_positions(self, session_id: str, coach_name: str | None = None) -> dict:
        """Read native-validated editable XI pairings for the in-possession phase only."""
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            coach = self._select_coach(save, coach_name)
            try:
                assignments = live_in_possession_source.inspect(snapshot, base, coach)
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'In-possession assignments rejected; no partial read returned: {exc}') from exc
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                    **assignments,
                    'evidence': 'owned_working_edit_session_native_XI_to_in_possession_slot_pairing',
                    'limitations': 'In-possession stored position and base-role selections from the retained '
                        'owned working edit session. Out-of-possession player mappings are not established. '
                        'Names follow verified compiled English branches; unknown masks and roles remain explicit. '
                        'Duplicate person slots are ambiguous and are not certified as individual assignments. '
                        'This does not prove foreground display, submission, eligibility or effective player '
                        'role overrides. Reads are non-atomic with consumed-byte and process rechecks.'}

    def get_managed_team_sheet(self, session_id: str, coach_name: str | None = None) -> dict:
        """Read existing managed edit-session selection without creating/applying one."""
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            coach = self._select_coach(save, coach_name)
            try:
                selection = live_team_sheet_source.inspect(snapshot, base, coach)
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'Managed team sheet rejected; no partial selection returned: {exc}') from exc
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                    **selection,
                    'evidence': 'active_human_existing_tactic_edit_session_current_selection',
                    'limitations': 'Current editable selection for the selected active human manager and team. '
                        'No edit session is created and no selection is applied. Null slots and duplicates '
                        'retain original order. This is not proof of submitted match registration, eligibility '
                        'or the lineup used in a played match. The bench is the editable selection\'s bench, '
                        'not a submitted match squad: bench_boundary_source session_stored_fixture_extent is '
                        'the end the game stored in the session for a fixture it bound to the session; '
                        'selection_screen_rule_for_cached_next_fixture is the count the selection screen '
                        'uses, the named-substitute cap of the team\'s cached next fixture (bench_fixture), '
                        'read when the session holds no end. A count the game substitutes when it evaluates '
                        'the selection for a fixture is not applied. Reads are non-atomic with consumed-byte '
                        'and process rechecks.'}

    def get_managed_penalty_takers(self,session_id: str,coach_name: str | None=None) -> dict:
        from . import managed_penalty_takers
        with self.lock,self._read_scope(session_id):
            process=self._current(session_id)
            tables=self._player_layout(process)
            snapshot,save,_=self._world_state(process,tables)
            coach=self._select_coach(save,coach_name)
            try:
                result=managed_penalty_takers.inspect(snapshot,tables[0]-players.RVA[0],coach)
                snapshot.verify()
                self._current(session_id)
            except (ValueError,IndexError,BridgeError) as error:
                raise BridgeError(f'Managed penalty priorities rejected; no partial read returned: {error}') from error
            return {'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),
                    'save':self._public_save(save),'coach':coach['name'],'club':coach['club'],**result,
                    'limitations':'Current managed-team stored penalty priority order, not an attribute ranking or past scorer list. '
                        'Pending working-edit overrides, final match selection, eligibility and shootout outcomes remain unestablished. '
                        'Loan/current-club links are separate from priority membership. No native functions, UI or game writes; '
                        'best-effort non-atomic reads with owner, canonical identity and consumed-byte rechecks.'}

    def _compose_fixture_player_checks(self, read, base, fixture_address, decoded,
                                       stage, picked, proposed, sheet, proposals):
        """Use one checked source scope; component failures never become clearance."""
        activation = fixture_signed_after_round.read_activation(
            read, base, read(fixture_address, 0x58), decoded['competition_address'])
        signed = fixture_player_checks.signed_after_round(activation)
        fixture_suspension.verify_native(read, base)
        manager = players.u64(read(base + 0x56D2D08, 8))
        people = database.table(read, base, 'people')
        assessment_people.verify_native(read, base)
        suspended = {}

        def suspension(index, native, secondary=None, kind=None):
            if index not in suspended:
                if not 0 <= index < people['count']:
                    raise ValueError('Fixture check PERSON index outside canonical table')
                person = world.pointer(read, people['start'] + index * 8)
                primary, _, identity, primary_id, secondary_id = assessment_people._person(
                    read, base, people, person)
                if (identity['native_identity']['database_index'] != index or primary_id != native
                        or (secondary is not None and secondary_id != secondary)
                        or (kind is not None and identity['record_kind'] != kind)):
                    raise ValueError('Fixture check PERSON identity changed')
                suspended[index] = fixture_suspension.check(read, base, primary,
                    identity['record_kind'], fixture_address=fixture_address, manager_address=manager)
            return suspended[index]

        picked_indices = None if picked is None else {
            row['person']['database_index'] for row in picked}
        for row in picked or []:
            person = row['person']
            row['selection_kind'] = 'currently_picked'
            row['checks'] = {
                'other_team_cup_history': fixture_player_checks.other_team_history(row['cup_history']),
                'ordinary_suspension': suspension(person['database_index'], person['native_id'],
                    person.get('secondary_id'), person['record_kind']),
                'signed_after_round': dict(signed)}
            row['overall_clearance'] = 'unknown'
        for row in proposed:
            identity = row['native_identity']
            index = identity['database_index']
            row['selection_kind'] = 'proposed_check'
            row['is_currently_picked'] = None if picked_indices is None else index in picked_indices
            calibrated = row['candidate_context']['state'] == 'compatible'
            row['checks'] = {
                'other_team_cup_history': fixture_player_checks.other_team_history(row['cup_history']),
                'ordinary_suspension': suspension(index, identity['native_id'], kind=row['record_kind'])
                    if calibrated else fixture_player_checks.unavailable('proposal_not_calibrated'),
                'signed_after_round': dict(signed) if calibrated else
                    fixture_player_checks.unavailable('proposal_not_calibrated')}
            row['overall_clearance'] = 'unknown'

    def get_fixture_player_checks(self, session_id: str, fixture_ref: str,
                                   coach_name: str | None = None,
                                   player_refs: list[str] | None = None) -> dict:
        """Match editable picks and optional checked proposals to resident cup history."""
        if player_refs is not None:
            self._validate_player_ref_list(player_refs)
            if len(player_refs) > 32:
                raise BridgeError('Supply 1 through 32 proposed player references.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.fixture_refs.get(fixture_ref) if isinstance(fixture_ref, str) else None
            if saved is None:
                raise BridgeError('Unknown or expired fixture reference. Call fm_find_fixtures again.')
            tables = self._player_layout(process)
            read, save, _ = self._world_state(process, tables)
            base = tables[0] - players.RVA[0]
            try:
                if saved['tables'] != tables:
                    raise ValueError('Fixture runtime layout changed')
                _, years, identity = fixtures.catalog(read, base)
                if identity != saved['catalog_identity']:
                    raise ValueError('Resident fixture inventory changed')
                entries, route = fixtures.bucket(read, years[saved['year']], saved['day'], saved['group'])
                if (route != saved['route'] or saved['slot'] >= len(entries)
                        or entries[saved['slot']] != saved['address']):
                    raise ValueError('Fixture bucket membership changed')
                decoded = fixtures.record(read, base, saved['address'], saved['year'], saved['day'], {})
                if decoded['identity'] != saved['identity']:
                    raise ValueError('Fixture identity changed')
                fixture, _, stage = fixtures.detail(read, base, saved['address'],
                    saved['year'], saved['day'], decoded, {}, True)
                coach = self._select_coach(save, coach_name)
                sheet = live_team_sheet_source.inspect(read, base, coach)
                coverage = {'source_state': 'unavailable', 'unavailable_reason': 'team_sheet_unavailable'}
                output, proposed = None, []
                proposals = {}
                if player_refs is not None:
                    people = database.table(read, base, 'people')
                    bound = self._bound_subjects(session_id, read, base, tables, people, player_refs)
                    for ref, (_, person) in bound.items():
                        proposals[ref] = {**person, 'candidate_context': cup_history.candidate_context(
                            read, base, self.player_refs[ref]['address'], person['record_kind'], coach['team_address'])}
                chosen = []
                selected_known = (sheet['source_state'] == 'available' and
                    sheet['role_boundary_state'] == 'native_first_11_and_stored_selected_end')
                if selected_known or player_refs is not None:
                    if coach['team_address'] not in decoded['teams']:
                        raise ValueError('Managed team is not a participant in this fixture')
                    if selected_known:
                        chosen = [slot for slot in sheet['slots']
                                  if slot['category'] in ('starting_position', 'bench') and slot['person']]
                    indices = {slot['person']['database_index'] for slot in chosen}
                    indices.update(person['native_identity']['database_index'] for person in proposals.values()
                                   if person['candidate_context']['state'] == 'compatible')
                    if decoded['competition'] is None:
                        coverage['unavailable_reason'] = 'fixture_competition_absent'
                        rows = None
                    else:
                        comp = decoded['competition']
                        comp_saved = {'address': decoded['competition_address'],
                                      'database_index': comp['database_index'],
                                      'native_id': comp['native_id'], 'random_id': comp.get('random_id')}
                        coverage, rows = cup_history.collect(read, base, comp_saved,
                            saved['address'], decoded, stage, indices)
                    def history(index):
                        return None if rows is None else cup_history.condition(
                            rows[index], sheet['team']['database_index'], coverage['phase']['rule_flags'])
                    if selected_known:
                        output = [{**slot, 'cup_history': history(slot['person']['database_index'])}
                                  for slot in chosen]
                    for ref in player_refs or []:
                        person = proposals[ref]
                        compatible = person['candidate_context']['state'] == 'compatible'
                        proposed.append({'player_ref': ref, **person, 'cup_history':
                            history(person['native_identity']['database_index']) if compatible and rows is not None else None,
                            'history_state': ('source_unavailable' if compatible and rows is None else
                                              'compatible_proposal_checked' if compatible else 'not_calibrated')})
                elif sheet['source_state'] == 'available':
                    coverage['unavailable_reason'] = 'selected_bench_boundary_unresolved'
                self._compose_fixture_player_checks(read, base, saved['address'], decoded, stage,
                    output, proposed, sheet, proposals)
                result = {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                          'save': self._public_save(save), 'coach': coach['name'], 'fixture_ref': fixture_ref,
                          'fixture': fixture, 'team': sheet['team'],
                          'selection_source_state': sheet['source_state'],
                          'duplicate_person_indices': sheet['duplicate_person_indices'],
                          'coverage': coverage, 'selected_players': output,
                          'historical_other_team_appearance_answer': 'not_established_by_this_source',
                          'native_condition_true_count': None if output is None or any(
                              row['cup_history'] is None or
                              row['cup_history']['native_other_team_cup_history_condition'] is None
                              for row in output) else sum(
                              row['cup_history']['native_other_team_cup_history_condition'] is True
                              for row in output),
                          'overall_clearance': 'unknown', 'team_selection_changed': False,
                          'overall_cup_clearance': 'not_assessed', 'match_eligibility': 'not_assessed',
                          'limitations': ('Current editable XI/bench, not submitted registration. Native flag1 '
                              'compares the resident PERSON row last-associated TEAM with this fixture TEAM, '
                              'without requiring positive appearances. Counters can accumulate across transfers; '
                              'neither a same-team row nor an absent row proves never appearing elsewhere. '
                              'Absent history is not zero appearances. Named signed-after-round activation and '
                              'ordinary suspension are separate scoped checks; enabled signing-date checks, '
                              'nonempty personal bans and overall clearance can remain unavailable. No '
                              'game function, lazy load, refresh or selection change is performed. Sources are reread '
                              'per request and consumed bytes rechecked; no historical absence is certified.')}
                if player_refs is not None:
                    result['proposed_players'] = proposed
                if len(json.dumps(result).encode()) > 2 * 1024 * 1024:
                    raise ValueError('Cup history response exceeds output budget')
                read.verify()
                self._current(session_id)
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Fixture player checks rejected; no partial read returned: {exc}') from exc
            return result

    def get_managed_tactics(self, session_id: str, coach_name: str | None = None,
                           include_formation: bool = False, include_instructions: bool = False,
                           include_roles: bool = False) -> dict:
        if any(type(flag) is not bool for flag in (include_formation, include_instructions, include_roles)):
            raise BridgeError('include_formation, include_instructions and include_roles must be booleans.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            coach = self._select_coach(save, coach_name)
            try:
                source, creators = prepared_tactics_source.inspect(snapshot, base, coach)
                formation_context = None
                if any(creators):
                    if include_formation:
                        formation_context = prepared_tactic_formations.load(snapshot, base)
                    if include_instructions:
                        prepared_tactic_instructions.verify_native(snapshot, base)
                    if include_roles:
                        prepared_tactic_roles.verify_native(snapshot, base)
                slots = []
                for index, address in enumerate(creators):
                    if address == 0:
                        slot = {'slot_index': index, 'state': 'null_slot', 'name': None,
                                'name_state': 'unavailable', 'phases': None}
                    else:
                        slot = {'slot_index': index, 'state': 'stored',
                                **prepared_tactics_fields.decode(snapshot, base, address)}
                        if include_roles:
                            for phase_name, phase in slot['phases'].items():
                                for position in phase['positions']:
                                    position['base_role'] = prepared_tactic_roles.decode(
                                        snapshot, address, phase_name, position['position_index'])
                        if include_formation:
                            for phase in slot['phases'].values():
                                masks = [position['native_mask'] for position in phase['positions']]
                                phase['formation'] = prepared_tactic_formations.identify(formation_context, masks)
                    if include_instructions:
                        if address:
                            slot.update(prepared_tactic_instructions.decode(snapshot, address))
                        else:
                            slot.update(mentality=None, team_instructions=None)
                    slots.append(slot)
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                raise BridgeError(f'Managed tactics rejected; no partial result returned: {exc}') from exc
            unavailable = ['current_match_assignment',
                           'localized_formation_name' if include_formation else 'official_formation']
            unavailable.extend(('localized_role_name', 'effective_player_role')
                               if include_roles else ('roles',))
            unavailable.extend(('instruction_phase_applicability', 'effective_instructions')
                               if include_instructions else ('instructions',))
            unavailable.extend(('familiarity', 'player_assignments'))
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                    **source, 'slots': slots,
                    'unavailable_fields': unavailable,
                    'evidence': 'canonical_managed_team_to_persisted_owner_tactics_with_primary_trained_selector',
                    'limitations': 'Prepared tactics stored for the selected active human manager and canonical team. '
                        'The selector means primary trained tactic; current match assignment is not established. '
                        'Positions cover both stored phases and retain unmapped native masks. '
                        'Optional formation details identify the first eligible numeric template for each phase. '
                        'Optional instruction details describe the shared stored selections and mentality. '
                        'Formation names use verified ordinary English for supported templates. '
                        'Base role names describe the stored position in each phase; each phase has its own role '
                        'and the role is the whole selection. '
                        'Localized names, individual overrides and effective match assignments remain unresolved. '
                        'Source absence is explicit and does not establish that no tactics exist. '
                        'Reads are non-atomic with consumed-byte and process rechecks; no tactic is generated.'}

    @staticmethod
    def _select_coach(record, coach_name):
        coaches = record["coaches"]
        if coach_name is not None:
            if not isinstance(coach_name, str) or not 1 <= len(coach_name) <= 256:
                raise BridgeError("coach_name must be a name returned by fm_get_save.")
            normalize = lambda value: " ".join(value.split()).casefold()
            coaches = [c for c in coaches if normalize(c["name"]) == normalize(coach_name)]
        if len(coaches) != 1:
            raise BridgeError("Select one active coach by name from fm_get_save.")
        return coaches[0]

    @staticmethod
    def _profile_policy(value):
        if not isinstance(value, str) or value not in ('required', 'available'):
            raise BridgeError('profile_policy must be required or available.')

    @staticmethod
    def _required_roster_identity(snapshot, address, tables, player, identity):
        """Return the PERSON words already checked by the strict rich decoder."""
        kind = player.get('record_kind', 'actual')
        person = address + (0x20 if kind == 'virtual' else players.person_offset(snapshot, address, tables))
        index, primary, secondary = tuple(int.from_bytes(snapshot(person + offset, 4), 'little')
                                          for offset in (8, 12, 16))
        expected_primary = identity[1] if kind in ('virtual', 'player_staff') else identity[0]
        if index == 0xFFFFFFFF or not primary or primary != expected_primary or secondary != identity[-1]:
            raise ValueError('Roster PERSON identity disagrees with its decoded player')
        return {'database_index': index, 'native_id': primary,
                'random_id': None if primary == secondary else secondary}

    @staticmethod
    def _available_player(snapshot, address, tables, player):
        base = tables[0] - players.RVA[0]
        kind = player.get('record_kind', 'actual')
        if kind == 'virtual':
            inspected = virtual_identity.inspect(snapshot, address, tables)
            native = inspected['native_identity']
            state, source = 'cached', 'cached_generated_profile'
        else:
            person = address + players.person_offset(snapshot, address, tables)
            index, primary, secondary = tuple(int.from_bytes(snapshot(person + offset, 4), 'little')
                                               for offset in (8, 12, 16))
            database.player_membership(snapshot, base, database.table(snapshot, base, 'people'), index, address)
            if not primary:
                raise ValueError('Player primary identity is missing')
            native = {'database_index': index, 'native_id': primary,
                      'random_id': None if primary == secondary else secondary}
            state, source = 'stored_direct', 'stored_direct'
        player.update(record_kind=kind, native_identity=native, profile_state=state,
                      unavailable_fields=[], field_sources={
                          'native_identity':'stored_direct',
                          **{field:source for field in ('name','display_name','birth_date','attributes')}})
        for field in ('clubs', 'profile', 'health'):
            if field in player:
                player['field_sources'][field] = ('stored_direct' if kind != 'virtual'
                                                   else 'existing_verified_virtual_reader')
        return player

    @staticmethod
    def _roster_player(snapshot, address, tables, include_clubs, team_cache, include_profile=False,
                       include_health=False, profile_policy='required'):
        table = world.pointer(snapshot, address)
        base = tables[0] - players.RVA[0]
        if table == base + world.TYPES['virtual_player'][0]:
            if profile_policy == 'available':
                player, identity = virtual.decode(snapshot, address, tables, include_clubs, include_profile,
                                                  profile_policy='available')
            else:
                player, identity = virtual.decode(snapshot, address, tables, include_clubs, include_profile)
            if include_health:
                if player.get('profile_state') == 'identity_only':
                    player['health'] = None
                    player['unavailable_fields'].append('health')
                    player['field_sources']['health'] = 'unavailable_from_verified_sources'
                else:
                    player['health'] = player_health.decode(snapshot, base, address, virtual=True)
                    if profile_policy == 'available':
                        player['field_sources']['health'] = 'existing_verified_virtual_health_reader'
            return player, identity
        player, identity = players.decode(snapshot, address, tables, include_profile)
        if include_health:
            player['health'] = player_health.decode(snapshot, base, address)
        if include_clubs:
            player['clubs'] = world.player_clubs(snapshot, base, address, team_cache, player_staff=True) if player.get('record_kind') == 'player_staff' else world.player_clubs(snapshot, base, address, team_cache)
        if profile_policy == 'available':
            Bridge._available_player(snapshot, address, tables, player)
        return player, identity

    @staticmethod
    def _roster_team(snapshot, base, address, row=None):
        index = int.from_bytes(snapshot(address + 8, 4), 'little')
        if row is None:
            row, binding = teams.by_index(snapshot, base, index)
            if binding['address'] != address:
                raise ValueError('Selected roster team membership changed')
        elif row['database_index'] != index:
            raise ValueError('Selected roster team index changed')
        owner = row['owner']
        club_owner = owner if owner and owner['kind'] in ('club', 'league_body_club') else None
        context = {'team_database_index':index, 'team_native_id':row['native_id'],
                   'owner_club_database_index':club_owner['database_index'] if club_owner else None,
                   'owner_club_native_id':club_owner['native_id'] if club_owner else None}
        return row, context

    @staticmethod
    def _roster_available_context(snapshot, address, tables, player, identity, context, index):
        if player.get('record_kind') == 'virtual':
            inspected = virtual_identity.inspect(snapshot, address, tables)
            if (inspected['identity'] != identity
                    or inspected['stored_team_index'] != context['team_database_index']):
                raise ValueError('Virtual stored team or identity disagrees with roster')
        player.update(roster_index=index, roster_context=dict(context))
        player['field_sources']['roster_context'] = 'checked_selected_team_roster'

    @staticmethod
    def _roster_accounting(players, policy):
        if policy == 'required':
            return {}
        counts = {state:0 for state in ('stored_direct','cached','identity_only')}
        for player in players:
            state = player.get('profile_state')
            if state not in counts:
                raise ValueError('Invalid roster profile availability state')
            counts[state] += 1
        return {'profile_policy':policy, 'native_slot_count':len(players), 'profile_counts':counts,
                'unavailable_profile_count':counts['identity_only'],
                'unavailable_profiles':[{'native_identity':p.get('native_identity'),
                                         'roster_index':p.get('roster_index'),
                                         'reason':p.get('profile_unavailable_reason'),
                                         'unavailable_fields':p.get('unavailable_fields',[])}
                                        for p in players if p.get('profile_state')=='identity_only'],
                'complete_base_profiles':counts['identity_only'] == 0,
                'base_profile_fields':['name','display_name','birth_date','attributes']}

    def _bind_person_index(self, index: int) -> dict | None:
        """The player binding of people-table index `index` (a "person:<index>" reference), as the
        roster tools make it, or None when it is not a supported player or nothing is attached."""
        if self.process is None or self.session is None:
            return None

        def bind():
            process = self.process
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            read, _, _ = self._world_state(process, tables)
            people = database.table(read, base, 'people')
            if not 0 <= index < people['count']:
                return None
            person_address = world.pointer(read, people['start'] + index * 8)
            primary, _, identity, _, _ = assessment_people._person(read, base, people, person_address)
            decoded, token = self._roster_player(read, primary, tables, False, {}, profile_policy='available')
            if decoded['native_identity'] != identity['native_identity']:
                return None
            read.verify()
            return self._player_binding(primary, decoded, token, tables, 'available')
        try:
            if self._reader is None:
                with self.lock, self._read_scope(self.session):
                    return bind()
            return bind()
        except (ValueError, IndexError, BridgeError, ReaderError):
            return None

    @staticmethod
    def _player_binding(address, player, identity, tables, policy):
        binding = {'address':address, 'identity':identity, 'tables':tables, 'world_bound':True,
                   'record_kind':player.get('record_kind','actual')}
        if policy == 'available':
            binding['database_index'] = player['native_identity']['database_index']
        if policy == 'available' and player.get('record_kind') == 'virtual':
            if not identity or identity[0] != virtual_identity.BINDING_KIND:
                raise ValueError('Invalid stored virtual reference identity')
            binding.update(binding_kind=virtual_identity.BINDING_KIND,
                           database_index=player['native_identity']['database_index'], person_offset=0x20)
        return binding

    def _referenced_club(self, snapshot, base, club_ref, tables):
        saved = self.club_refs.get(club_ref)
        if not saved:
            raise BridgeError('Unknown or expired club reference. Call fm_find_clubs again.')
        try:
            if saved['tables'] != tables:
                raise ValueError('Club layout changed')
            info = database.table(snapshot, base, 'clubs')
            database.club_membership(snapshot, base, info, saved['database_index'], saved['address'])
            club, identity = world.club(snapshot, base, saved['address'])
            if identity != saved['identity']:
                raise ValueError('Club identity changed')
        except (ValueError, IndexError) as exc:
            self.club_refs.pop(club_ref, None)
            raise BridgeError(f'Club reference rejected: {exc}') from exc
        return club, saved['address'], saved['database_index'], identity

    def get_club_finances(self, session_id: str, coach_name: str | None = None,
                          club_ref: str | None = None, *, include_details: bool = False,
                          include_ffp_projection: bool = False) -> dict:
        from . import financial_details
        if type(include_ffp_projection) is not bool:
            raise BridgeError('include_ffp_projection must be a boolean.')
        if type(include_details) is not bool:
            raise BridgeError('include_details must be a boolean.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, record, _ = self._world_state(process, tables)
            if club_ref is not None and coach_name is not None:
                raise BridgeError('Select either club_ref or coach_name, not both.')
            if club_ref is None:
                coach = self._select_coach(record, coach_name)
                club_address = world.pointer(snapshot, coach['team_address'] + 0x30)
                club = coach['club']
            else:
                club, club_address, _, _ = self._referenced_club(snapshot, base, club_ref, tables)
            try:
                finance = club_finance.decode(snapshot, base, club_address)
                if include_details:
                    finance['details'] = financial_details.club_details(snapshot, base, club_address, self.plugin_identity[0])
                if include_ffp_projection:
                    from . import ffp_projection
                    try:
                        finance['ffp_projection'] = ffp_projection.project(
                            snapshot.read, snapshot, base, club_address, self.plugin_identity[0])
                    except ffp_projection.UnsupportedProjection as exc:
                        finance['ffp_projection'] = {'state': 'unavailable', 'reason': str(exc), 'competitions': None}
                snapshot.verify()
            except (ValueError, IndexError) as exc:
                raise BridgeError(f'Club finances rejected: {exc}') from exc
            self._current(session_id)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(record), 'club': club, 'finances': finance,
                    'limitations': club_finance.LIMITATIONS}

    def check_transfer_budget(self, session_id: str, upfront_fee_gbp: int,
                              coach_name: str | None = None, club_ref: str | None = None) -> dict:
        if type(upfront_fee_gbp) is not int or not 0 <= upfront_fee_gbp <= 2147483647:
            raise BridgeError('upfront_fee_gbp must be an integer from 0 to 2147483647.')
        result = self.get_club_finances(session_id, coach_name, club_ref)
        budget = result['finances']['current_transfer_budget']
        amount = budget['amount']
        return {'session_id': session_id, 'observed_at': result['observed_at'], 'save': result['save'],
                'club': result['club'], 'currency': 'GBP', 'upfront_fee': upfront_fee_gbp,
                'current_transfer_budget': budget,
                'fits_current_transfer_budget': None if amount is None else upfront_fee_gbp <= amount,
                'budget_after_upfront_fee': None if amount is None else amount - upfront_fee_gbp,
                'limitations': 'Arithmetic comparison of one upfront transfer fee with the decoded native current budget. '
                               'Does not include wages, agent/signing fees, instalments, conditional payments, pending offers, '
                               'seller demands, registration rules or board approval. Unknown budgets stay unclassified. '
                               'No offer is submitted and no budget is changed.'}

    def check_wage_budget(self, session_id: str, additional_weekly_wage_gbp: int,
                          coach_name: str | None = None, club_ref: str | None = None) -> dict:
        if type(additional_weekly_wage_gbp) is not int or not 0 <= additional_weekly_wage_gbp <= 2147483647:
            raise BridgeError('additional_weekly_wage_gbp must be an integer from 0 to 2147483647.')
        result = self.get_club_finances(session_id, coach_name, club_ref)
        budget = result['finances']['remaining_weekly_wage_budget']
        amount = budget['amount']
        return {'session_id': session_id, 'observed_at': result['observed_at'], 'save': result['save'],
                'club': result['club'], 'currency': 'GBP', 'period': 'week',
                'additional_weekly_wage': additional_weekly_wage_gbp,
                'remaining_weekly_wage_budget': budget,
                'fits_remaining_wage_budget': None if amount is None else additional_weekly_wage_gbp <= amount,
                'budget_after_additional_wage': None if amount is None else amount - additional_weekly_wage_gbp,
                'limitations': 'Arithmetic comparison with the native remaining wage budget from stored spending. '
                               'No spending refresh is triggered. The additional amount is supplied by you; this does not '
                               'price bonuses, contributions, future commitments, transfer fees or a complete offer. '
                               'It does not establish board approval. Unknown budgets stay unclassified. '
                               'No offer is submitted and no budget is changed.'}

    def query_transfer_offers(self, session_id: str, *, person_native_id=None, team_native_id=None,
                              club_native_id=None, raw_state_codes=None, limit=50, cursor=None) -> dict:
        from .live_transfer_offers import query
        try:
            return query(self, session_id, person_native_id=person_native_id, team_native_id=team_native_id,
                         club_native_id=club_native_id, raw_state_codes=raw_state_codes, limit=limit, cursor=cursor)
        except (ValueError, IndexError) as exc:
            raise BridgeError(f'Live transfer-offer query rejected: {exc}') from exc

    def get_wage_contributions(self, session_id: str, coach_name: str | None = None,
                               club_ref: str | None = None, all_clubs: bool = False) -> dict:
        if type(all_clubs) is not bool:
            raise BridgeError('all_clubs must be a boolean.')
        if all_clubs and (coach_name is not None or club_ref is not None):
            raise BridgeError('all_clubs cannot be combined with coach_name or club_ref.')
        if coach_name is not None and club_ref is not None:
            raise BridgeError('Select either club_ref or coach_name, not both.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, record, _ = self._world_state(process, tables)
            club, address = None, None
            if not all_clubs:
                if club_ref is None:
                    coach = self._select_coach(record, coach_name)
                    address = world.pointer(snapshot, coach['team_address'] + 0x30)
                    club = coach['club']
                else:
                    club, address, _, _ = self._referenced_club(snapshot, base, club_ref, tables)
            try:
                rows, entities, examined = wage_contributions.decode(snapshot, base, address)
                snapshot.verify()
            except (ValueError, IndexError) as exc:
                raise BridgeError(f'Wage contributions rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            used = {row[key] for row in rows for key in ('person_key', 'payer_key', 'recipient_key')}
            public = {}
            stores = {'club': self.club_refs, 'player': self.player_refs, 'staff': self.staff_refs}
            for kind, refs in stores.items():
                if len(refs) + sum(key[0] == kind for key in used) > 1000:
                    refs.clear()
            for key in used:
                kind, entity_address = key
                entity = entities[key]
                public[key] = dict(entity['record'])
                if kind == 'unsupported_person':
                    continue
                ref = secrets.token_urlsafe(12)
                stores[kind][ref] = {'address': entity_address, 'identity': entity['identity'],
                                    'database_index': entity['database_index'], 'tables': tables, 'world_bound': True}
                public[key][kind + '_ref'] = ref
            results = [{k: v for k, v in row.items() if not k.endswith('_key')} |
                       {'person': public[row['person_key']], 'payer': public[row['payer_key']],
                        'recipient': public[row['recipient_key']]} for row in rows]
            outgoing = sum(row['weekly_amount'] for row in rows if row['direction'] in ('outgoing', 'both'))
            incoming = sum(row['weekly_amount'] for row in rows if row['direction'] in ('incoming', 'both'))
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(record), 'club': club, 'scope': 'all_clubs' if all_clubs else 'selected_club',
                    'currency': 'GBP', 'period': 'week', 'contributions': results, 'count': len(results),
                    'native_records_examined': examined, 'complete_native_list': True,
                    'total_weekly_contributions': sum(row['weekly_amount'] for row in rows),
                    'outgoing_weekly_total': None if all_clubs else outgoing,
                    'incoming_weekly_total': None if all_clubs else incoming,
                    'net_outgoing_weekly_total': None if all_clubs else outgoing - incoming,
                    'unresolved_person_count': sum(row['person']['state'] != 'decoded' for row in results),
                    'evidence': 'live_transfer_manager_weekly_wage_contributions',
                    'limitations': wage_contributions.LIMITATIONS}

    def get_club_squads(self, session_id: str, coach_name: str | None = None,
                        club_ref: str | None = None) -> dict:
        if club_ref is not None and coach_name is not None:
            raise BridgeError('Select either club_ref or coach_name, not both.')
        with self.lock:
            reference_checks = []
            with self._roster_publication_scope(session_id, reference_checks) as (snapshot, record, tables):
                base = tables[0] - players.RVA[0]
                club_index, club_identity = None, None
                if club_ref is None:
                    coach = self._select_coach(record, coach_name)
                    club_address = world.pointer(snapshot, coach['team_address'] + 0x30)
                    club = coach['club']
                else:
                    binding = self.club_refs.get(club_ref) if isinstance(club_ref, str) else None
                    reference_checks.append(('club_refs', club_ref, deepcopy(binding)))
                    club, club_address, club_index, club_identity = self._referenced_club(snapshot, base, club_ref, tables)
                pending = []
                try:
                    for address in world.vector(snapshot, club_address + 0x18, 64):
                        world.typed(snapshot, base, address, 'team')
                        if world.pointer(snapshot, address + 0x30) != club_address:
                            raise ValueError('Club team backlink disagrees')
                        identity = snapshot(address + 8, 12)
                        native_type = int.from_bytes(snapshot(address + 0x28, 2), 'little')
                        label = {0: 'Senior', 266: 'U21', 268: 'U18'}.get(native_type, 'Other squad')
                        count = len(world.vector(snapshot, address + 0x38, 256))
                        pending.append((address, identity, native_type, label, count))
                    snapshot.verify()
                except (ValueError, IndexError) as exc:
                    raise BridgeError(f'Club squads rejected: {exc}') from exc
                public_save = self._public_save(record)
            result, published = [], {}
            for address, identity, native_type, label, count in pending:
                ref = secrets.token_urlsafe(12)
                published[ref] = {'address': address, 'identity': identity, 'tables': tables,
                                       'club_address': club_address, 'label': label,
                                       'club_database_index': club_index, 'club_identity': club_identity}
                result.append({'team_ref': ref, 'label': label, 'native_type': native_type,
                               'count': count, 'is_managed_team': any(address == c['team_address'] for c in record['coaches'])})
            if len(self.team_refs) + len(pending) > 256:
                self.team_refs.clear()
            self.team_refs.update(published)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': public_save, 'club': club, 'squads': result,
                    'evidence': 'live_club_table_to_team_vector' if club_ref is not None else 'managed_club_native_team_vector',
                    'limitations': 'Labels Senior/U21/U18 were crosschecked on Newcastle in the pinned build. Other squad types remain unlabelled. Counts include virtual players; rosters can overlap and differ from UI filters.'}

    def get_team_squad(self, session_id: str, team_ref: str, include_clubs: bool = False, include_profile: bool = False, include_health: bool = False, profile_policy: str = "required") -> dict:
        self._profile_policy(profile_policy)
        if type(include_health) is not bool:
            raise BridgeError('include_health must be a boolean.')
        if type(include_profile) is not bool:
            raise BridgeError('include_profile must be a boolean.')
        if type(include_clubs) is not bool:
            raise BridgeError('include_clubs must be a boolean.')
        with self.lock:
            saved = deepcopy(self.team_refs.get(team_ref)) if isinstance(team_ref, str) else None
            if not saved:
                raise BridgeError('Unknown or expired team reference. Call fm_get_club_squads, fm_get_competition_teams or fm_get_competition_registrations again.')
            reference_checks = [('team_refs', team_ref, saved)]
            with self._roster_publication_scope(session_id, reference_checks) as (snapshot, record, tables):
                pending, team_cache = [], {}
                try:
                    address = saved['address']
                    if tables != saved['tables'] or snapshot(address + 8, 12) != saved['identity']:
                        raise ValueError('Team identity changed')
                    base = tables[0] - players.RVA[0]
                    team_row = None
                    if saved.get('source') in ('competition', 'national'):
                        team_row, binding = teams.by_index(snapshot, base, saved['database_index'])
                        if any(binding[key] != saved[key] for key in binding):
                            raise ValueError('Team or owner identity changed')
                        owner = team_row['owner']
                        club = ({'name': owner['name'], 'short_name': owner['short_name']}
                                if owner and owner['kind'] in ('club', 'league_body_club') else None)
                    else:
                        world.typed(snapshot, tables[0] - players.RVA[0], address, 'team')
                        club_address = world.pointer(snapshot, address + 0x30)
                        if club_address != saved['club_address'] or address not in world.vector(snapshot, club_address + 0x18, 64):
                            raise ValueError('Team club relationship changed')
                        base = tables[0] - players.RVA[0]
                        club, club_identity = world.club(snapshot, base, club_address)
                        if saved.get('club_database_index') is not None:
                            info = database.table(snapshot, base, 'clubs')
                            database.club_membership(snapshot, base, info, saved['club_database_index'], club_address)
                            if club_identity != saved['club_identity']:
                                raise ValueError('Team club identity changed')
                    context = None
                    if profile_policy == 'available':
                        canonical, context = self._roster_team(snapshot, base, address, team_row)
                        if team_row is None:
                            team_row = canonical
                    for index, player_address in enumerate(world.vector(snapshot, address + 0x38, 256)):
                        player, identity = self._roster_player(snapshot, player_address, tables, include_clubs, team_cache,
                                                              include_profile, include_health, profile_policy)
                        if profile_policy == 'required':
                            player['native_identity'] = self._required_roster_identity(
                                snapshot, player_address, tables, player, identity)
                        if context is not None:
                            self._roster_available_context(snapshot, player_address, tables, player, identity, context, index)
                        pending.append((player_address, player, identity))
                    prepared = [self._player_binding(address, player, identity, tables, profile_policy)
                                for address, player, identity in pending]
                    accounting = self._roster_accounting([player for _, player, _ in pending], profile_policy)
                    snapshot.verify()
                except (ValueError, IndexError, BridgeError) as exc:
                    self.team_refs.pop(team_ref, None)
                    raise BridgeError(f'Team squad rejected; no partial roster returned: {exc}') from exc
                public_save = self._public_save(record)
            result, published = [], {}
            for (address, player, identity), binding in zip(pending, prepared):
                ref = secrets.token_urlsafe(12)
                published[ref] = binding
                result.append({**player, 'player_ref': ref})
            if len(self.player_refs) + len(pending) > 1000:
                self.player_refs.clear()
            self.player_refs.update(published)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': public_save, 'team_ref': team_ref, 'label': saved['label'],
                    'club': club, **({'team': team_row} if team_row is not None else {}),
                    'players': result, 'count': len(result), 'complete_native_roster': True,
                    'virtual_player_count': sum(p.get('record_kind') == 'virtual' for p in result),
                    **accounting,
                    'evidence': 'save_bound_database_team_roster' if team_row is not None else 'save_bound_club_team_roster_with_actual_and_virtual_players',
                    'limitations': 'Native roster membership is not ownership or match eligibility. Rich virtual fields require existing identity-matched game caches; no profile is generated by this reader. Non-atomic reads with byte rechecks.' + (
                        ' Available policy also returns checked identity-only virtual records with null unavailable expanded fields; roster context does not establish contract/current club or loan status.'
                        if profile_policy == 'available' else '')}

    def find_players(self, session_id: str, name: str, max_mib: int = 256,
                     max_matches: int = 20, cursor: str | None = None) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            integer(max_mib, 1, 1024, "max_mib")
            integer(max_matches, 1, 100, "max_matches")
            if not isinstance(name, str) or not 3 <= len(name) <= 128 or any(ord(c) < 32 or ord(c) == 127 for c in name):
                raise BridgeError("Player name must contain 3–128 characters and no controls.")
            try:
                name.encode("utf-8")
            except UnicodeError as exc:
                raise BridgeError("Player name must be valid Unicode.") from exc
            tables = self._player_layout(process)
            address = 0
            if cursor is not None and (not isinstance(cursor, str) or not cursor):
                raise BridgeError('Search cursor must be a nonempty string.')
            if cursor is not None:
                saved = self.player_cursors.get(cursor)
                if not saved or saved["name"] != name or saved["tables"] != tables:
                    raise BridgeError("Player cursor is invalid or belongs to a different search.")
                address = saved["address"]
            native = self._run("scan-session", process,
                               "--writable-only", "--start-address", str(address),
                               "--max-bytes", str(max_mib * 1024 * 1024), "--max-matches", str(max_matches),
                               "--hex-needle", tables[0].to_bytes(8, "little").hex(),
                               "--player-primary", str(tables[0]), "--player-playing", str(tables[1]),
                               "--player-person", str(tables[2]), "--player-query", name)
            if not isinstance(native.get("matches"), list) or native.get("stop_reason") not in {
                "byte_budget", "match_limit", "address_space_end"
            }:
                raise BridgeError("Incompatible native player reader. Rebuild the helper.")
            if len(self.player_refs) + len(native["matches"]) > 1000:
                self.player_refs.clear()
            results, rejected = [], 0
            for candidate in native["matches"]:
                candidate_address = int(candidate["address"], 16)
                try:
                    record, identity = self._decode_player(process, candidate_address, tables)
                    if not any(name.lower() in record[k].lower() for k in ('name', 'display_name')):
                        raise BridgeError("Player name changed during search.")
                except BridgeError:
                    # A process change must fail the entire operation, not return partial data.
                    self._current(session_id)
                    rejected += 1
                    continue
                ref = secrets.token_urlsafe(12)
                self.player_refs[ref] = {"address": candidate_address, "identity": identity, "tables": tables}
                record["player_ref"] = ref
                results.append(record)
            next_cursor = None
            if native["stop_reason"] == "byte_budget":
                next_address = int(native["next_address"], 16)
                if next_address <= address:
                    raise BridgeError("Native player scan made no forward progress.")
                if len(self.player_cursors) >= 100:
                    self.player_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.player_cursors[next_cursor] = {"address": next_address, "name": name, "tables": tables}
            self._current(session_id)
            return {"session_id": session_id, "observed_at": datetime.now(timezone.utc).isoformat(),
                    "players": results, "rejected_candidates": rejected, "scan": native.get("scan"),
                    "stop_reason": native["stop_reason"], "next_cursor": next_cursor,
                    "absence_proven": False, "save_identity": "unverified",
                    "verification": "Exact plugin fingerprint and runtime types; field layout crosschecked against two displayed profiles.",
                    "limitations": "Readable writable memory; non-atomic. Results may include retained objects. Reattach after changing saves. Match-limit scans have no continuation; narrow the name. ASCII case-insensitive substring; non-ASCII spelling is exact."}

    def get_database_catalog(self, session_id: str, include_auxiliary: bool = False) -> dict:
        if type(include_auxiliary) is not bool:
            raise BridgeError('include_auxiliary must be a boolean.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            snapshot, record, _ = self._world_state(process, tables)
            try:
                counts = {kind: database.table(snapshot, tables[0] - players.RVA[0], kind)['count']
                          for kind in database.TABLES}
                auxiliary = None
                if include_auxiliary:
                    from . import auxiliary_database_tables
                    auxiliary = auxiliary_database_tables.inspect(snapshot, tables[0] - players.RVA[0])
                snapshot.verify()
            except (ValueError, IndexError) as exc:
                raise BridgeError(f'Database catalog rejected: {exc}') from exc
            result = {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(record), 'native_table_counts': counts,
                    'evidence': 'typed_database_singletons_and_rechecked_vector_headers',
                    'limitations': 'Counts include multiple record types, including retired people and virtual players. They are not counts of active players or fully decoded records. This catalog does not expose every field in those tables. Non-atomic reads.'}

            if include_auxiliary:
                result['auxiliary_tables'] = auxiliary
            return result

    def find_save_players(self, session_id: str, name: str, max_matches: int = 20,
                          record_budget: int = 200000, cursor: str | None = None) -> dict:
        return self._find_database_records(session_id, 'people', name, max_matches, record_budget, cursor)

    def find_clubs(self, session_id: str, name: str, max_matches: int = 20,
                    record_budget: int = 200000, cursor: str | None = None) -> dict:
        return self._find_database_records(session_id, 'clubs', name, max_matches, record_budget, cursor)

    def find_staff(self, session_id: str, name: str, max_matches: int = 20,
                   record_budget: int = 200000, cursor: str | None = None) -> dict:
        return self._find_database_records(session_id, 'staff', name, max_matches, record_budget, cursor)

    @staticmethod
    def _geographic_record(read, base, address, kind, include_details=False):
        decoders = {'language': languages, 'weather': weather, 'media_source': media_sources}
        if kind in decoders:
            decoder = decoders[kind]
            row,binding = decoder.record(read,base,address,include_details=include_details)
            return row,binding,{}
        row,binding,children = local_regions.record(read,base,address,include_details=include_details)
        links = {'languages':children}
        if include_details:
            pointer = players.u64(read(address+0x50,8))
            links['weather'] = geography.identity(read,base,pointer,'weather') if pointer else None
        return row,binding,links

    @staticmethod
    def _geographic_bindings(binding, links):
        return [binding,*links.get('languages',[]),links.get('weather')]

    def _reserve_geographic_references(self, bindings):
        count = len({(b['kind'],b['address']) for b in bindings if b is not None})
        if count>10000:raise BridgeError('Geographic result exceeds the reference bound; reduce max_matches.')
        if len(self.geographic_refs)+count>10000:self.geographic_refs.clear()

    def _publish_geographic(self, row, binding, tables, links=None, ref=None, published=None):
        published = {} if published is None else published
        key = (binding['kind'],binding['address'])
        ref = ref or published.get(key) or secrets.token_urlsafe(12)
        published[key] = ref
        self.geographic_refs[ref] = {**binding,'tables':tables}
        result = {**row,binding['kind']+'_ref':ref}
        if binding['kind']=='local_region' and 'languages' in row:
            result['languages'] = [{**entry,'language':self._publish_geographic(entry['language'],child,tables,published=published)
                                    if child else None} for entry,child in zip(row['languages'],links['languages'],strict=True)]
            child = links.get('weather')
            if child:result['weather'] = self._publish_geographic(row['weather'],child,tables,published=published)
        return result

    @staticmethod
    def _city_geographic_bindings(read, base, address):
        result = {}
        for kind,offset in (('language',0x30),('local_region',0x38),('weather',0x28)):
            pointer = players.u64(read(address+offset,8))
            result[kind] = geography.identity(read,base,pointer,kind) if pointer else None
        return result

    def find_languages(self, session_id: str, name: str | None = None, native_id: int | None = None,
                       nation: str | None = None, nation_native_id: int | None = None,
                       maximum_difficulty: int | None = None, minimum_influence: int | None = None,
                       is_deleted: bool | None = None, max_matches: int = 20,
                       record_budget: int = 1000, cursor: str | None = None) -> dict:
        return self._find_geographic(session_id,'language',name,native_id,nation,nation_native_id,max_matches,record_budget,cursor,
                                    dict(maximum_difficulty=maximum_difficulty,minimum_influence=minimum_influence,is_deleted=is_deleted))

    def find_local_regions(self, session_id: str, name: str | None = None, native_id: int | None = None,
                           nation: str | None = None, nation_native_id: int | None = None,
                           minimum_population: int | None = None, max_matches: int = 20,
                           record_budget: int = 1000, cursor: str | None = None,
                           weather_native_id: int | None = None) -> dict:
        return self._find_geographic(session_id,'local_region',name,native_id,nation,nation_native_id,max_matches,record_budget,cursor,
                                    dict(minimum_population=minimum_population,weather_native_id=weather_native_id))

    def find_media_sources(self, session_id, name=None, native_id=None, max_matches=20, record_budget=1000, cursor=None):
        return self._find_geographic(session_id, 'media_source', name, native_id, None, None,
                                     max_matches, record_budget, cursor, {})

    def get_media_source(self, session_id, media_source_ref):
        return self._get_geographic(session_id, media_source_ref, 'media_source')

    def find_weather_profiles(self, session_id: str, name: str | None = None, native_id: int | None = None,
                              max_matches: int = 20, record_budget: int = 1000, cursor: str | None = None) -> dict:
        return self._find_geographic(session_id,'weather',name,native_id,None,None,max_matches,record_budget,cursor,{})

    def _find_geographic(self, session_id, kind, name, native_id, nation, nation_native_id,
                         max_matches, record_budget, cursor, selectors):
        integer(max_matches,1,100,'max_matches');integer(record_budget,1,1000,'record_budget')
        for label,value in (('native_id',native_id),('nation_native_id',nation_native_id)):
            if value is not None:integer(value,1,0xFFFFFFFF,label)
        for label,value in selectors.items():
            if value is None:continue
            if label=='is_deleted':
                if type(value) is not bool:raise BridgeError('is_deleted must be a boolean.')
            elif label=='weather_native_id':integer(value,1,0xFFFFFFFF,label)
            else:integer(value,0,0x7FFFFFFF if label=='minimum_population' else 20,label)
        for label,value in (('name',name),('nation',nation)):
            if value is None:continue
            if not isinstance(value,str) or not 1<=len(value)<=128 or any(ord(c)<32 or ord(c)==127 for c in value):
                raise BridgeError(f'{label} must contain 1–128 characters and no controls.')
            try:
                if len(value.encode('utf-8'))>128:raise BridgeError(f'{label} must fit within 128 UTF-8 bytes.')
            except UnicodeError as exc:raise BridgeError(f'{label} must be valid Unicode.') from exc
        if cursor is not None and (not isinstance(cursor,str) or not cursor):raise BridgeError('Geographic cursor must be a nonempty string.')
        table_kind = geography.FIELDS[kind][1]
        criteria = dict(name=name,native_id=native_id,nation=nation,nation_native_id=nation_native_id,**selectors)
        scope = {'language':languages.SCOPE,'local_region':local_regions.SCOPE,'weather':weather.SCOPE,'media_source':media_sources.SCOPE}[kind]
        with self.lock,self._read_scope(session_id):
            process = self._current(session_id);tables = self._player_layout(process);base = tables[0]-players.RVA[0]
            snapshot,save,_ = self._world_state(process,tables)
            try:
                info = database.table(snapshot,base,table_kind);start = 0
                if cursor is not None:
                    saved = self.database_cursors.get(cursor)
                    if not saved or saved['kind']!=table_kind or saved['identity']!=info['identity'] or saved.get('criteria')!=criteria:
                        raise ValueError('Geographic cursor expired or belongs to a different query')
                    start = saved['index']
                end,pending,unnamed,cache = start,[],0,{}
                while end<min(info['count'],start+record_budget):
                    address = world.pointer(snapshot,info['start']+end*8)
                    row,binding,_ = self._geographic_record(snapshot,base,address,kind)
                    if binding['database_index']!=end:raise ValueError('Geographic index disagrees with table slot')
                    end+=1;unnamed+=not row['name']
                    if native_id is not None and row['native_id']!=native_id:continue
                    if name is not None and (not row['name'] or name.casefold() not in row['name'].casefold()):continue
                    if kind=='language':
                        if selectors['is_deleted'] is not None and row['is_deleted']!=selectors['is_deleted']:continue
                        if selectors['maximum_difficulty'] is not None and int.from_bytes(snapshot(address+0x3C,1),'little',signed=True)>selectors['maximum_difficulty']:continue
                        if selectors['minimum_influence'] is not None and int.from_bytes(snapshot(address+0x3B,1),'little',signed=True)<selectors['minimum_influence']:continue
                    elif kind=='local_region':
                        if selectors['minimum_population'] is not None and int.from_bytes(snapshot(address+0x58,4),'little',signed=True)<selectors['minimum_population']:continue
                        if selectors['weather_native_id'] is not None:
                            pointer = players.u64(snapshot(address+0x50,8))
                            if not pointer or geography.identity(snapshot,base,pointer,'weather')['native_id']!=selectors['weather_native_id']:continue
                    if nation is not None or nation_native_id is not None:
                        pointer = players.u64(snapshot(address+(0x28 if kind=='language' else 0x48),8))
                        if not pointer:continue
                        if pointer not in cache:cache[pointer] = geography.record(snapshot,base,pointer,'nation')
                        country = cache[pointer]
                        if nation_native_id is not None and country['native_id']!=nation_native_id:continue
                        if nation is not None and not any(nation.casefold() in (country[k] or '').casefold() for k in ('short_name','abbreviation')):continue
                    pending.append(self._geographic_record(snapshot,base,address,kind,include_details=True))
                    if len(pending)==max_matches:break
                snapshot.verify()
            except (ValueError,IndexError,KeyError,TypeError) as exc:
                raise BridgeError(f'{kind.title()} query rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            self._reserve_geographic_references([b for _,binding,links in pending for b in self._geographic_bindings(binding,links)])
            published = {}
            rows = [self._publish_geographic(row,binding,tables,links,published=published) for row,binding,links in pending]
            next_cursor = None
            if end<info['count']:
                if len(self.database_cursors)>=100:self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = dict(kind=table_kind,criteria=criteria,identity=info['identity'],index=end)
            return {'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),'save':self._public_save(save),
                    ('weather_profiles' if kind=='weather' else table_kind):rows,'count':len(rows),'criteria':criteria,'total_records':info['count'],
                    'scanned_records':end-start,'unnamed_records_examined':unnamed,'start_index':start,'next_index':end,
                    'next_cursor':next_cursor,'stop_reason':'table_end' if end==info['count'] else 'match_limit' if len(pending)==max_matches else 'record_budget',
                    'complete_table_scan':start==0 and end==info['count'],'ordering':'native_database_index',
                    'evidence':'save_bound_geographic_table_and_rechecked_stored_fields','limitations':scope}

    def get_language(self, session_id: str, language_ref: str) -> dict:
        return self._get_geographic(session_id,language_ref,'language')

    def get_local_region(self, session_id: str, local_region_ref: str) -> dict:
        return self._get_geographic(session_id,local_region_ref,'local_region')

    def get_weather_profile(self, session_id: str, weather_ref: str) -> dict:
        return self._get_geographic(session_id,weather_ref,'weather')

    def _get_geographic(self, session_id, ref, kind):
        with self.lock,self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.geographic_refs.get(ref) if isinstance(ref,str) else None
            if not saved or saved['kind']!=kind:raise BridgeError(f'Unknown {kind} reference. Search again.')
            tables = self._player_layout(process);base = tables[0]-players.RVA[0]
            snapshot,save,_ = self._world_state(process,tables)
            try:
                if tables!=saved['tables']:raise ValueError('Geographic runtime layout changed')
                info = database.table(snapshot,base,geography.FIELDS[kind][1])
                if not 0<=saved['database_index']<info['count']:raise ValueError('Geographic index outside table')
                address = world.pointer(snapshot,info['start']+saved['database_index']*8)
                row,binding,links = self._geographic_record(snapshot,base,address,kind,include_details=True)
                if any(binding[k]!=saved[k] for k in binding):raise ValueError('Geographic identity or membership changed')
                snapshot.verify()
            except (ValueError,IndexError,KeyError,TypeError) as exc:
                self.geographic_refs.pop(ref,None)
                raise BridgeError(f'{kind.title()} reference rejected: {exc}') from exc
            self._current(session_id)
            self._reserve_geographic_references(self._geographic_bindings(binding,links))
            result = self._publish_geographic(row,binding,tables,links,ref=ref)
            return {'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),'save':self._public_save(save),
                    ('weather_profile' if kind=='weather' else kind):result,'save_identity':'native_binding_rechecked','evidence':'rechecked_geographic_identity_membership_and_fields',
                    'limitations':{'language':languages.SCOPE,'local_region':local_regions.SCOPE,'weather':weather.SCOPE,'media_source':media_sources.SCOPE}[kind]}

    def _publish_city(self, row, binding, tables, ref=None, links=None, published=None):
        ref = ref or secrets.token_urlsafe(12)
        self.city_refs[ref] = {**binding,'tables':tables}
        result = {**row,'city_ref':ref}
        if links is not None:
            for kind,child in links.items():
                if child:result[kind] = self._publish_geographic(row[kind],child,tables,published=published)
        return result

    @staticmethod
    def _stadium_links(snapshot, base, address):
        linked = {}
        for kind,offset in (('city',0x60),('owner_club',0x90),('nearby_stadium',0x68)):
            pointer = players.u64(snapshot(address+offset,8))
            if not pointer:
                linked[kind] = None
                continue
            if pointer < 4096 or pointer % 8: raise ValueError(f'Invalid stadium {kind} pointer')
            if kind == 'city':
                linked[kind] = cities.record(snapshot,base,pointer)
            elif kind == 'nearby_stadium':
                linked[kind] = stadiums.record(snapshot,base,pointer)
            else:
                info = database.table(snapshot,base,'clubs')
                index = int.from_bytes(snapshot(pointer+8,4),'little')
                database.club_membership(snapshot,base,info,index,pointer)
                row,identity = world.club(snapshot,base,pointer)
                row = {**row,'native_id':identity[0],'database_index':index,'kind':'club','name_source':'stored_native_strings'}
                linked[kind] = (row,{'address':pointer,'identity':identity,'database_index':index,'world_bound':True})
        return linked

    def _reserve_stadium_references(self, links, parent_count):
        if len(self.stadium_refs)+parent_count+sum(item['nearby_stadium'] is not None for item in links)>10000:
            self.stadium_refs.clear()
        if len(self.city_refs)+sum(item['city'] is not None for item in links)>10000:
            self.city_refs.clear()
        if len(self.club_refs)+sum(item['owner_club'] is not None for item in links)>1000:
            self.club_refs.clear()

    def _publish_stadium(self, row, binding, tables, ref=None, links=None):
        ref = ref or secrets.token_urlsafe(12)
        self.stadium_refs[ref] = {**binding, 'tables':tables}
        result = {**row, 'stadium_ref':ref}
        if links is not None:
            for kind,linked in links.items():
                if linked is None:
                    result[kind] = None
                elif kind == 'city':
                    result[kind] = self._publish_city(*linked,tables)
                elif kind == 'nearby_stadium':
                    result[kind] = self._publish_stadium(*linked,tables)
                else:
                    club_ref = secrets.token_urlsafe(12)
                    self.club_refs[club_ref] = {**linked[1],'tables':tables}
                    result[kind] = {**linked[0],'club_ref':club_ref}
        return result

    def find_currencies(self, session_id: str, name: str | None = None, native_id: int | None = None,
                        max_matches: int = 20, record_budget: int = 1000, cursor: str | None = None) -> dict:
        integer(max_matches, 1, 100, 'max_matches'); integer(record_budget, 1, 1000, 'record_budget')
        if native_id is not None: integer(native_id, 1, 0xFFFFFFFF, 'native_id')
        if name is not None:
            if not isinstance(name, str) or not 1 <= len(name) <= 128 or any(ord(c)<32 or ord(c)==127 for c in name):
                raise BridgeError('name must contain 1–128 characters and no controls.')
            try:
                if len(name.encode('utf-8')) > 128: raise BridgeError('name must fit within 128 UTF-8 bytes.')
            except UnicodeError as exc:
                raise BridgeError('name must be valid Unicode.') from exc
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise BridgeError('Currency cursor must be a nonempty string.')
        criteria = dict(name=name, native_id=native_id)
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id); tables = self._player_layout(process); base = tables[0]-players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                info = database.table(snapshot, base, 'currencies'); start = 0
                if cursor is not None:
                    saved = self.database_cursors.get(cursor)
                    if (not saved or saved['kind'] != 'currencies' or saved['identity'] != info['identity']
                            or saved.get('criteria') != criteria):
                        raise ValueError('Currency cursor expired or belongs to a different query')
                    start = saved['index']
                end, pending, unnamed = start, [], 0
                while end < min(info['count'], start+record_budget):
                    row, binding = currencies.by_index(snapshot, base, end)
                    end += 1; unnamed += not row['name']
                    if native_id is not None and row['native_id'] != native_id: continue
                    if name is not None and (not row['name'] or name.casefold() not in row['name'].casefold()): continue
                    pending.append((row, binding))
                    if len(pending) == max_matches: break
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Currency query rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            if len(self.currency_refs)+len(pending) > 10000: self.currency_refs.clear()
            results = []
            for row, binding in pending:
                ref = secrets.token_urlsafe(12)
                self.currency_refs[ref] = {**binding, 'tables': tables}
                results.append({**row, 'currency_ref': ref})
            next_cursor = None
            if end < info['count']:
                if len(self.database_cursors) >= 100: self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = dict(kind='currencies', criteria=criteria, identity=info['identity'], index=end)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(), 'save': self._public_save(save),
                    'currencies': results, 'count': len(results), 'criteria': criteria, 'total_records': info['count'],
                    'scanned_records': end-start, 'unnamed_records_examined': unnamed, 'start_index': start, 'next_index': end,
                    'next_cursor': next_cursor, 'complete_table_scan': start == 0 and end == info['count'],
                    'stop_reason': 'table_end' if end == info['count'] else 'match_limit' if len(pending) == max_matches else 'record_budget',
                    'ordering': 'native_database_index', 'evidence': 'save_bound_currency_table_and_rechecked_fields',
                    'limitations': currencies.SCOPE}

    def _currency_from_ref(self, snapshot, base, tables, ref, *, include_details=False):
        saved = self.currency_refs.get(ref) if isinstance(ref, str) else None
        if not saved: raise ValueError('Unknown currency reference. Call fm_find_currencies again')
        try:
            if saved['tables'] != tables: raise ValueError('Currency runtime layout changed')
            row, binding = currencies.by_index(snapshot, base, saved['database_index'], include_details=include_details)
            if any(binding[key] != saved[key] for key in binding): raise ValueError('Currency identity or membership changed')
        except (ValueError, IndexError, KeyError, TypeError):
            self.currency_refs.pop(ref, None)
            raise
        return {**row, 'currency_ref': ref}

    def get_currency(self, session_id: str, currency_ref: str) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id); tables = self._player_layout(process); base = tables[0]-players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                row = self._currency_from_ref(snapshot, base, tables, currency_ref, include_details=True)
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Currency reference rejected: {exc}') from exc
            self._current(session_id)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(), 'save': self._public_save(save),
                    'currency': row, 'save_identity': 'native_binding_rechecked',
                    'evidence': 'rechecked_currency_identity_membership_and_fields', 'limitations': currencies.SCOPE}

    def convert_currency(self, session_id: str, amount: str, from_currency_ref: str, to_currency_ref: str) -> dict:
        if not isinstance(amount, str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,18})?', amount):
            raise BridgeError('amount must be a plain decimal string with at most 18 whole and 18 fractional digits.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id); tables = self._player_layout(process); base = tables[0]-players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                source = self._currency_from_ref(snapshot, base, tables, from_currency_ref)
                target = self._currency_from_ref(snapshot, base, tables, to_currency_ref)
                base_currency = wages.base_currency(snapshot, base)
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Currency conversion rejected: {exc}') from exc
            self._current(session_id)
            invalid = [field for field, row in (('from_currency', source), ('to_currency', target))
                       if row['exchange_rate']['value'] is None or row['exchange_rate']['value'] <= 0]
            converted = None
            if not invalid:
                with localcontext() as context:
                    context.prec = 50
                    exact = (Fraction(Decimal(amount))*Fraction(target['exchange_rate']['value'])
                             / Fraction(source['exchange_rate']['value']))
                    converted = format(Decimal(exact.numerator)/Decimal(exact.denominator), 'f')
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(), 'save': self._public_save(save),
                    'amount': amount, 'from_currency': source, 'to_currency': target, 'converted_amount': converted,
                    'state': 'unavailable_rate' if invalid else 'calculated', 'unavailable_rates': invalid,
                    'rate_source': 'stored_current_exchange_rates', 'rate_basis': base_currency,
                    'formula': 'amount * to_rate / from_rate', 'decimal_precision': 50,
                    'evidence': 'same_read_rechecked_currency_identities_rates_and_GBP_basis',
                    'limitations': 'Arithmetic on current stored game rates with 50 significant decimal digits. '
                                   'No currency display rounding, historical interpolation, runtime formatter override, '
                                   'offer validation or real-world exchange quote. Zero, negative and non-finite rates cannot convert.'}

    def _reserve_stadium_change_references(self, pending):
        if len(self.stadium_change_refs) + len(pending) > 10000:
            self.stadium_change_refs.clear()
        if len(self.team_refs) + sum(links['team'] is not None for _, _, links in pending) > 10000:
            self.team_refs.clear()
        count = sum(links[field] is not None for _, _, links in pending for field in stadium_changes.STADIUM_LINKS)
        if len(self.stadium_refs) + count > 10000:
            self.stadium_refs.clear()

    def _publish_stadium_change(self, row, binding, links, tables, ref=None):
        ref = ref or secrets.token_urlsafe(12)
        self.stadium_change_refs[ref] = {**binding, 'tables': tables}
        result = {**row, 'stadium_change_ref': ref}
        for field, linked in links.items():
            if linked is None:
                result[field] = None
            elif field == 'team':
                team, team_binding = linked
                team_ref = secrets.token_urlsafe(12)
                self.team_refs[team_ref] = {**team_binding, 'tables': tables, 'source': 'competition',
                                           'label': f"{team['kind']} type {team['native_type_code']}"}
                result[field] = {**team, 'team_ref': team_ref}
            else:
                result[field] = self._publish_stadium(*linked, tables)
        return result

    def find_stadium_changes(self, session_id: str, native_id: int | None = None,
                             team_native_id: int | None = None, stadium_native_id: int | None = None,
                             type_code: int | None = None, max_matches: int = 20,
                             record_budget: int = 1000, cursor: str | None = None) -> dict:
        integer(max_matches, 1, 100, 'max_matches')
        integer(record_budget, 1, 1000, 'record_budget')
        for field, value in (('native_id', native_id), ('team_native_id', team_native_id), ('stadium_native_id', stadium_native_id)):
            if value is not None:
                integer(value, 1, 0xFFFFFFFF, field)
        if type_code is not None:
            integer(type_code, -128, 127, 'type_code')
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise BridgeError('Stadium-change cursor must be a nonempty string.')
        criteria = dict(native_id=native_id, team_native_id=team_native_id,
                        stadium_native_id=stadium_native_id, type_code=type_code)
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                info = database.table(snapshot, base, 'stadium_changes')
                start = 0
                if cursor is not None:
                    saved = self.database_cursors.get(cursor)
                    if (not saved or saved['kind'] != 'stadium_changes' or saved['identity'] != info['identity']
                            or saved.get('criteria') != criteria):
                        raise ValueError('Stadium-change cursor expired or belongs to a different query')
                    start = saved['index']
                end, pending = start, []
                while end < min(info['count'], start + record_budget):
                    row, binding, links = stadium_changes.by_index(snapshot, base, end)
                    end += 1
                    if native_id is not None and row['native_id'] != native_id:
                        continue
                    if type_code is not None and row['type']['native_code'] != type_code:
                        continue
                    if team_native_id is not None and (row['team'] is None or row['team']['native_id'] != team_native_id):
                        continue
                    if stadium_native_id is not None and not any(
                            row[field] and row[field]['native_id'] == stadium_native_id for field in stadium_changes.STADIUM_LINKS):
                        continue
                    pending.append((row, binding, links))
                    if len(pending) == max_matches:
                        break
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Stadium-change query rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            self._reserve_stadium_change_references(pending)
            results = [self._publish_stadium_change(*item, tables) for item in pending]
            next_cursor = None
            if end < info['count']:
                if len(self.database_cursors) >= 100:
                    self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = dict(kind='stadium_changes', criteria=criteria,
                                                          identity=info['identity'], index=end)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'stadium_changes': results, 'count': len(results), 'criteria': criteria,
                    'total_records': info['count'], 'scanned_records': end-start, 'start_index': start, 'next_index': end,
                    'next_cursor': next_cursor, 'complete_table_scan': start == 0 and end == info['count'],
                    'stop_reason': 'table_end' if end == info['count'] else 'match_limit' if len(pending) == max_matches else 'record_budget',
                    'ordering': 'native_database_index', 'evidence': 'save_bound_stadium_change_table_and_rechecked_fields',
                    'limitations': stadium_changes.SCOPE}

    def get_stadium_change(self, session_id: str, stadium_change_ref: str) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.stadium_change_refs.get(stadium_change_ref) if isinstance(stadium_change_ref, str) else None
            if not saved:
                raise BridgeError('Unknown stadium-change reference. Call fm_find_stadium_changes again.')
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                if tables != saved['tables']:
                    raise ValueError('Stadium-change runtime layout changed')
                row, binding, links = stadium_changes.by_index(snapshot, base, saved['database_index'])
                if any(binding[key] != saved[key] for key in binding):
                    raise ValueError('Stadium-change identity or membership changed')
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                self.stadium_change_refs.pop(stadium_change_ref, None)
                raise BridgeError(f'Stadium-change reference rejected: {exc}') from exc
            self._current(session_id)
            self._reserve_stadium_change_references([(row, binding, links)])
            result = self._publish_stadium_change(row, binding, links, tables, ref=stadium_change_ref)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'stadium_change': result, 'save_identity': 'native_binding_rechecked',
                    'evidence': 'rechecked_stadium_change_identity_membership_and_fields', 'limitations': stadium_changes.SCOPE}

    def find_stadiums(self, session_id: str, name: str | None = None, native_id: int | None = None,
                      minimum_capacity: int | None = None, is_extinct: bool | None = None,
                      is_training_ground: bool | None = None, max_matches: int = 20,
                      record_budget: int = 1000, cursor: str | None = None) -> dict:
        integer(max_matches,1,100,'max_matches')
        integer(record_budget,1,1000,'record_budget')
        if native_id is not None: integer(native_id,1,0xFFFFFFFF,'native_id')
        if minimum_capacity is not None: integer(minimum_capacity,0,0x7FFFFFFF,'minimum_capacity')
        if name is not None:
            if not isinstance(name,str) or not 1 <= len(name) <= 128 or any(ord(c)<32 or ord(c)==127 for c in name):
                raise BridgeError('name must contain 1–128 characters and no controls.')
            try:
                if len(name.encode('utf-8')) > 128: raise BridgeError('name must fit within 128 UTF-8 bytes.')
            except UnicodeError as exc:
                raise BridgeError('name must be valid Unicode.') from exc
        for field,value in (('is_extinct',is_extinct),('is_training_ground',is_training_ground)):
            if value is not None and type(value) is not bool: raise BridgeError(f'{field} must be a boolean.')
        if cursor is not None and (not isinstance(cursor,str) or not cursor):
            raise BridgeError('Stadium cursor must be a nonempty string.')
        criteria = dict(name=name,native_id=native_id,minimum_capacity=minimum_capacity,
                        is_extinct=is_extinct,is_training_ground=is_training_ground)
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0]-players.RVA[0]
            snapshot,save,_ = self._world_state(process,tables)
            try:
                info = database.table(snapshot,base,'stadiums')
                start = 0
                if cursor is not None:
                    saved = self.database_cursors.get(cursor)
                    if (not saved or saved['kind'] != 'stadiums' or saved['identity'] != info['identity']
                            or saved.get('criteria') != criteria):
                        raise ValueError('Stadium cursor expired or belongs to a different query')
                    start = saved['index']
                end,pending,unnamed = start,[],0
                while end < min(info['count'],start+record_budget):
                    row,binding = stadiums.by_index(snapshot,base,end)
                    end += 1
                    names = [row[k] for k in ('name','continental_name') if row[k]]
                    unnamed += not names
                    if native_id is not None and row['native_id'] != native_id: continue
                    if name is not None and not any(name.casefold() in v.casefold() for v in names): continue
                    if is_extinct is not None and row['is_extinct'] != is_extinct: continue
                    if is_training_ground is not None and row['is_training_ground'] != is_training_ground: continue
                    if minimum_capacity is not None:
                        capacity = int.from_bytes(snapshot(binding['address']+0x7C,4),'little',signed=True)
                        if capacity < minimum_capacity: continue
                    row,binding = stadiums.record(snapshot,base,binding['address'],include_details=True)
                    links = self._stadium_links(snapshot,base,binding['address'])
                    pending.append((row,binding,links))
                    if len(pending) == max_matches: break
                snapshot.verify()
            except (ValueError,IndexError,KeyError,TypeError) as exc:
                raise BridgeError(f'Stadium query rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            self._reserve_stadium_references([links for _,_,links in pending],len(pending))
            results = [self._publish_stadium(row,binding,tables,links=links) for row,binding,links in pending]
            next_cursor = None
            if end < info['count']:
                if len(self.database_cursors)>=100: self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = dict(kind='stadiums',criteria=criteria,
                                                          identity=info['identity'],index=end)
            return {'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),
                    'save':self._public_save(save),'stadiums':results,'count':len(results),'criteria':criteria,
                    'total_stadium_records':info['count'],'scanned_records':end-start,'unnamed_records_examined':unnamed,
                    'start_index':start,'next_index':end,'next_cursor':next_cursor,
                    'stop_reason':'table_end' if end==info['count'] else 'match_limit' if len(pending)==max_matches else 'record_budget',
                    'complete_table_scan':start==0 and end==info['count'],'ordering':'native_database_index',
                    'evidence':'save_bound_stadium_table_and_rechecked_stored_fields','limitations':stadiums.SCOPE}

    def get_stadium(self, session_id: str, stadium_ref: str) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.stadium_refs.get(stadium_ref) if isinstance(stadium_ref,str) else None
            if not saved: raise BridgeError('Unknown stadium reference. Call fm_find_stadiums or fm_find_fixtures again.')
            tables = self._player_layout(process)
            base = tables[0]-players.RVA[0]
            snapshot,save,_ = self._world_state(process,tables)
            try:
                if tables != saved['tables']: raise ValueError('Stadium runtime layout changed')
                row,binding = stadiums.by_index(snapshot,base,saved['database_index'],include_details=True)
                if any(binding[k] != saved[k] for k in binding): raise ValueError('Stadium identity or membership changed')
                links = self._stadium_links(snapshot,base,binding['address'])
                snapshot.verify()
            except (ValueError,IndexError,KeyError,TypeError) as exc:
                self.stadium_refs.pop(stadium_ref,None)
                raise BridgeError(f'Stadium reference rejected: {exc}') from exc
            self._current(session_id)
            self._reserve_stadium_references([links],1)
            stadium = self._publish_stadium(row,binding,tables,ref=stadium_ref,links=links)
            return {'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),
                    'save':self._public_save(save),'stadium':stadium,
                    'save_identity':'native_binding_rechecked','evidence':'rechecked_stadium_identity_membership_and_fields',
                    'limitations':stadiums.SCOPE}

    def find_cities(self, session_id: str, name: str | None = None, native_id: int | None = None,
                    nation: str | None = None, nation_native_id: int | None = None,
                    minimum_attraction: int | None = None, is_deleted: bool | None = None,
                    max_matches: int = 20, record_budget: int = 1000, cursor: str | None = None,
                    local_region_native_id: int | None = None, language_native_id: int | None = None,
                    weather_native_id: int | None = None) -> dict:
        integer(max_matches,1,100,'max_matches')
        integer(record_budget,1,1000,'record_budget')
        for field,value in (('native_id',native_id),('nation_native_id',nation_native_id),
                            ('local_region_native_id',local_region_native_id),('language_native_id',language_native_id),('weather_native_id',weather_native_id)):
            if value is not None:integer(value,1,0xFFFFFFFF,field)
        if minimum_attraction is not None:integer(minimum_attraction,0,20,'minimum_attraction')
        if is_deleted is not None and type(is_deleted) is not bool:raise BridgeError('is_deleted must be a boolean.')
        for field,value in (('name',name),('nation',nation)):
            if value is None:continue
            if not isinstance(value,str) or not 1<=len(value)<=128 or any(ord(c)<32 or ord(c)==127 for c in value):
                raise BridgeError(f'{field} must contain 1–128 characters and no controls.')
            try:
                if len(value.encode('utf-8'))>128:raise BridgeError(f'{field} must fit within 128 UTF-8 bytes.')
            except UnicodeError as exc:raise BridgeError(f'{field} must be valid Unicode.') from exc
        if cursor is not None and (not isinstance(cursor,str) or not cursor):raise BridgeError('City cursor must be a nonempty string.')
        criteria = dict(name=name,native_id=native_id,nation=nation,nation_native_id=nation_native_id,
                        minimum_attraction=minimum_attraction,is_deleted=is_deleted,
                        local_region_native_id=local_region_native_id,language_native_id=language_native_id,weather_native_id=weather_native_id)
        with self.lock,self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0]-players.RVA[0]
            snapshot,save,_ = self._world_state(process,tables)
            try:
                info = database.table(snapshot,base,'cities')
                start = 0
                if cursor is not None:
                    saved = self.database_cursors.get(cursor)
                    if (not saved or saved['kind']!='cities' or saved['identity']!=info['identity'] or saved.get('criteria')!=criteria):
                        raise ValueError('City cursor expired or belongs to a different query')
                    start = saved['index']
                end,pending,unnamed,cache = start,[],0,{}
                while end<min(info['count'],start+record_budget):
                    row,binding = cities.by_index(snapshot,base,end)
                    end+=1;unnamed+=not row['name']
                    if native_id is not None and row['native_id']!=native_id:continue
                    if name is not None and (not row['name'] or name.casefold() not in row['name'].casefold()):continue
                    if is_deleted is not None and row['is_deleted']!=is_deleted:continue
                    if minimum_attraction is not None and int.from_bytes(snapshot(binding['address']+0x54,1),'little',signed=True)<minimum_attraction:continue
                    if nation is not None or nation_native_id is not None:
                        pointer = players.u64(snapshot(binding['address']+0x20,8))
                        if not pointer:continue
                        if pointer<4096 or pointer%8:raise ValueError('Invalid city nation pointer')
                        key = ('nation',pointer)
                        if key not in cache:cache[key] = geography.record(snapshot,base,pointer,'nation')
                        country = cache[key]
                        if nation_native_id is not None and country['native_id']!=nation_native_id:continue
                        if nation is not None and not any(nation.casefold() in (country[k] or '').casefold() for k in ('short_name','abbreviation')):continue
                    matches_links = True
                    for kind,offset,selector in (('language',0x30,language_native_id),('local_region',0x38,local_region_native_id),('weather',0x28,weather_native_id)):
                        if selector is None:continue
                        pointer = players.u64(snapshot(binding['address']+offset,8))
                        if not pointer:
                            matches_links = False;break
                        key = (kind,pointer)
                        if key not in cache:cache[key] = geography.record(snapshot,base,pointer,kind)
                        if cache[key]['native_id']!=selector:
                            matches_links = False;break
                    if not matches_links:continue
                    row,binding = cities.record(snapshot,base,binding['address'],include_details=True,context_cache=cache)
                    links = self._city_geographic_bindings(snapshot,base,binding['address'])
                    pending.append((row,binding,links))
                    if len(pending)==max_matches:break
                snapshot.verify()
            except (ValueError,IndexError,KeyError,TypeError) as exc:
                raise BridgeError(f'City query rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            if len(self.city_refs)+len(pending)>10000:self.city_refs.clear()
            self._reserve_geographic_references([b for _,_,links in pending for b in links.values()])
            published = {}
            results = [self._publish_city(row,binding,tables,links=links,published=published) for row,binding,links in pending]
            next_cursor = None
            if end<info['count']:
                if len(self.database_cursors)>=100:self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = dict(kind='cities',criteria=criteria,identity=info['identity'],index=end)
            return {'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),
                    'save':self._public_save(save),'cities':results,'count':len(results),'criteria':criteria,
                    'total_city_records':info['count'],'scanned_records':end-start,'unnamed_records_examined':unnamed,
                    'start_index':start,'next_index':end,'next_cursor':next_cursor,
                    'stop_reason':'table_end' if end==info['count'] else 'match_limit' if len(pending)==max_matches else 'record_budget',
                    'complete_table_scan':start==0 and end==info['count'],'ordering':'native_database_index',
                    'evidence':'save_bound_city_table_and_rechecked_stored_fields','limitations':cities.SCOPE}

    def get_city(self, session_id: str, city_ref: str) -> dict:
        with self.lock,self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.city_refs.get(city_ref) if isinstance(city_ref,str) else None
            if not saved:raise BridgeError('Unknown city reference. Call fm_find_cities or fm_get_stadium again.')
            tables = self._player_layout(process)
            base = tables[0]-players.RVA[0]
            snapshot,save,_ = self._world_state(process,tables)
            try:
                if tables!=saved['tables']:raise ValueError('City runtime layout changed')
                row,binding = cities.by_index(snapshot,base,saved['database_index'],include_details=True)
                if any(binding[k]!=saved[k] for k in binding):raise ValueError('City identity or membership changed')
                links = self._city_geographic_bindings(snapshot,base,binding['address'])
                snapshot.verify()
            except (ValueError,IndexError,KeyError,TypeError) as exc:
                self.city_refs.pop(city_ref,None)
                raise BridgeError(f'City reference rejected: {exc}') from exc
            self._current(session_id)
            self._reserve_geographic_references(links.values())
            city = self._publish_city(row,binding,tables,ref=city_ref,links=links)
            return {'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),
                    'save':self._public_save(save),'city':city,
                    'save_identity':'native_binding_rechecked','evidence':'rechecked_city_identity_membership_and_fields',
                    'limitations':cities.SCOPE}

    def find_competitions(self, session_id: str, name: str | None = None,
                          native_id: int | None = None, max_matches: int = 20,
                          record_budget: int = 1000, cursor: str | None = None,
                          nation: str | None = None, continent: str | None = None,
                          type_code: int | None = None, gender: str | None = None,
                          is_extinct: bool | None = None) -> dict:
        """Scan typed competition records without executing game code."""
        integer(max_matches, 1, 100, 'max_matches')
        integer(record_budget, 1, 1000, 'record_budget')
        if native_id is not None:
            integer(native_id, 1, 0xFFFFFFFF, 'native_id')
        for label, value in (('name', name), ('nation', nation), ('continent', continent)):
            if value is None:
                continue
            if (not isinstance(value, str) or not 1 <= len(value) <= 128
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise BridgeError(f'{label} must contain 1–128 characters and no controls.')
            try:
                if len(value.encode('utf-8')) > 128:
                    raise BridgeError(f'{label} must fit within 128 UTF-8 bytes.')
            except UnicodeError as exc:
                raise BridgeError(f'{label} must be valid Unicode.') from exc
        if type_code is not None:
            integer(type_code, -128, 127, 'type_code')
        if gender is not None and gender not in ('male', 'female'):
            raise BridgeError('gender must be male or female.')
        if is_extinct is not None and type(is_extinct) is not bool:
            raise BridgeError('is_extinct must be a boolean.')
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise BridgeError('Competition cursor must be a nonempty string.')
        criteria = {'name': name, 'native_id': native_id, 'nation': nation, 'continent': continent,
                    'type_code': type_code, 'gender': gender, 'is_extinct': is_extinct}
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                info = database.table(snapshot, base, 'competitions')
                start = 0
                if cursor is not None:
                    saved = self.database_cursors.get(cursor)
                    if (not saved or saved['kind'] != 'competitions'
                            or saved['identity'] != info['identity'] or saved.get('criteria') != criteria):
                        raise ValueError('Competition cursor expired or belongs to a different query')
                    start = saved['index']
                end, pending, unnamed = start, [], 0
                context_cache = {}
                while end < min(info['count'], start + record_budget):
                    row = competitions.by_index(snapshot, base, end, include_context=True, context_cache=context_cache)
                    address = world.pointer(snapshot, info['start'] + end * 8)
                    end += 1
                    names = [row[key] for key in ('name', 'short_name', 'abbreviation') if row[key]]
                    unnamed += not names
                    if native_id is not None and row['native_id'] != native_id:
                        continue
                    if name is not None and not any(name.casefold() in value.casefold() for value in names):
                        continue
                    context = row['context']
                    location_matches = True
                    for field, value, keys in (('nation', nation, ('short_name', 'abbreviation')),
                                               ('continent', continent, ('name', 'abbreviation'))):
                        if value is None:
                            continue
                        location = context[field] or {}
                        if not any(value.casefold() in location[key].casefold() for key in keys if location.get(key)):
                            location_matches = False
                            break
                    if not location_matches:
                        continue
                    if type_code is not None and context['competition_type']['native_code'] != type_code:
                        continue
                    if gender is not None and context['gender']['native_code'] != {'male': 0, 'female': 1}[gender]:
                        continue
                    if is_extinct is not None and context['is_extinct'] != is_extinct:
                        continue
                    pending.append((address, row))
                    if len(pending) == max_matches:
                        break
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Competition query rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            if len(self.competition_refs) + len(pending) > 10000:
                self.competition_refs.clear()
            results = []
            for address, row in pending:
                ref = secrets.token_urlsafe(12)
                self.competition_refs[ref] = {'address': address, 'native_id': row['native_id'], 'random_id': row['random_id'],
                    'database_index': row['database_index'], 'tables': tables}
                results.append({**row, 'competition_ref': ref})
            next_cursor = None
            if end < info['count']:
                if len(self.database_cursors) >= 100:
                    self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = {'kind': 'competitions', 'criteria': criteria,
                    'identity': info['identity'], 'index': end}
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': self._public_save(save), 'competitions': results, 'count': len(results),
                'criteria': criteria, 'total_competition_records': info['count'],
                'scanned_records': end - start, 'unnamed_records_examined': unnamed,
                'start_index': start, 'next_index': end, 'next_cursor': next_cursor,
                'stop_reason': 'table_end' if end == info['count'] else
                               'match_limit' if len(pending) == max_matches else 'record_budget',
                'complete_table_scan': start == 0 and end == info['count'],
                'ordering': 'native_database_index',
                'evidence': 'save_bound_competition_table_and_rechecked_stored_names',
                'limitations': competitions.SCOPE}

    def get_managed_league_age_exemptions(self, session_id: str, coach_name: str | None = None, *,
                                         include_registration: bool = False) -> dict:
        """Read current league age exemption and optional exact native registration predicate."""
        if type(include_registration) is not bool:
            raise BridgeError('include_registration must be a boolean.')
        if coach_name is not None and (not isinstance(coach_name, str) or not coach_name.strip() or len(coach_name) > 128):
            raise BridgeError('coach_name must be a nonempty string of at most 128 characters.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            coach = self._select_coach(save, coach_name)
            try:
                result, pending = league_age_exemptions.collect(
                    snapshot, base, tables, coach['team_address'], save['current_date'])
                if include_registration:
                    context, registration_binding = player_registration_source.current_league_context(
                        snapshot, base, coach, save['current_date'])
                    result['registration_context'] = context
                    for row, binding in zip(result['players'], pending, strict=True):
                        row['registration'] = player_registration_source.current_predicate(
                            snapshot, binding['address'] if binding else 0,
                            row['record_kind'], registration_binding)
                    result['registration_counts'] = {
                        name: sum(row['registration']['native_predicate_result'] is value
                                  for row in result['players'])
                        for name, value in (('native_predicate_true', True),
                                            ('native_predicate_false', False), ('unavailable', None))}
                    result['registration_scope'] = (
                        'Current native PLAYER registration predicate D32054(mode1) for the bound '
                        'managed Premier League TEAM/rule/selector. Committed25 and temporary26 '
                        'can both be native-true and remain distinct. False may coexist with age '
                        'exemption and is not an exclusion verdict. Outside-club and unsupported '
                        'contexts remain unavailable. Marker historical season/submission date, '
                        'complete official submitted population and full fixture eligibility are '
                        'not evaluated. No game functions or context creation.')
                result.update(session_id=session_id, observed_at=datetime.now(timezone.utc).isoformat(),
                              save=self._public_save(save), as_of_date=save['current_date'],
                              coach=coach['name'], club=coach['club'])
                if len(json.dumps(result, ensure_ascii=True).encode()) > 2*1024*1024:
                    raise ValueError('League age response exceeds supported budget')
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'League age exemption source rejected; no partial result returned: {exc}') from exc
            if len(self.player_refs) + sum(binding is not None for binding in pending) > 1000:
                self.player_refs.clear()
            for row, binding in zip(result['players'], pending, strict=True):
                if binding is not None:
                    ref = secrets.token_urlsafe(12)
                    self.player_refs[ref] = binding
                    row['player_ref'] = ref
            return result

    def get_league_player_statistics(self, session_id: str, competition_ref: str,
                                     player_refs: list[str]) -> dict:
        """Join checked input players into a single complete current COMP pool."""
        from . import league_player_lookup as lookup, league_player_ranking as totals
        import hashlib
        self._validate_player_ref_list(player_refs)
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.competition_refs.get(competition_ref) if isinstance(competition_ref, str) else None
            if not saved:
                raise BridgeError('Unknown competition reference; call fm_find_competitions again')
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            read, save, _ = self._world_state(process, tables)
            try:
                if saved['tables'] != tables:
                    raise ValueError('Competition layout changed')
                people = database.table(read, base, 'people')
                subjects = {}
                for ref in dict.fromkeys(player_refs):
                    binding = self.player_refs.get(ref)
                    if binding is None:
                        raise ValueError('Unknown or expired player reference')
                    try:
                        subjects[ref] = lookup.bound_subject(read, base, tables, people, binding)
                    except assessment_people.StalePlayerReference:
                        read.verify()
                        self._current(session_id)
                        self.player_refs.pop(ref, None)
                        raise
                coverage, candidates = totals.collect(read, base, saved)
                result = lookup.project(coverage, candidates,
                    [(ref, *subjects[ref]) for ref in player_refs])
                pin = None
                if coverage['source_state'] == 'available':
                    pin = hashlib.sha256(json.dumps({
                        'process': (process.pid, process.started), 'save': self._public_save(save),
                        'tables': tables, 'source': coverage,
                        'candidates': [(c['person_index'], c['source_ordinal'], c['_raw_hex'], c['_identity'])
                                       for c in candidates],
                    }, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
                result.update(session_id=session_id, observed_at=datetime.now(timezone.utc).isoformat(),
                              save=self._public_save(save), competition_ref=competition_ref,
                              source=coverage, source_pin=pin,
                              scope='requested checked PERSON identities in the exact current COMP-owned counter population')
                if len(json.dumps(result, ensure_ascii=True).encode()) > 2 * 1024 * 1024:
                    raise ValueError('Competition player-statistics response exceeds budget')
                read.verify()
                self._current(session_id)
            except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
                raise BridgeError(f'League player-statistics lookup rejected; no partial result returned: {exc}') from exc
            return result

    def rank_league_players(self, session_id: str, competition_ref: str,
                            sort_by: str = 'starting_appearances', order: str = 'ascending',
                            minutes_over: int | None = None, limit: int = 10,
                            page_size: int = 100, cursor: str | None = None,
                            source_pin: str | None = None) -> dict:
        from . import league_player_ranking as totals
        import hashlib
        try:
            totals.options(sort_by,order,minutes_over,limit)
            integer(page_size,1,100,'page_size')
            if cursor is not None and (not isinstance(cursor,str) or not cursor):
                raise ValueError('cursor must be a nonempty string or null')
            if source_pin is not None and (not isinstance(source_pin,str) or not source_pin):
                raise ValueError('source_pin must be a nonempty string or null')
            if (cursor is None)!=(source_pin is None):
                raise ValueError('Continuations require both cursor and source_pin; initial requests require neither')
        except (ValueError,TypeError) as exc:
            raise BridgeError(str(exc)) from exc
        criteria={'competition_ref':competition_ref,'sort_by':sort_by,'order':order,
                  'minutes_over':minutes_over,'limit':limit}
        with self.lock,self._read_scope(session_id):
            process=self._current(session_id)
            saved=self.competition_refs.get(competition_ref) if isinstance(competition_ref,str) else None
            if not saved:raise BridgeError('Unknown competition reference; call fm_find_competitions again')
            tables=self._player_layout(process);base=tables[0]-players.RVA[0]
            snapshot,save,_=self._world_state(process,tables)
            try:
                if saved['tables']!=tables:raise ValueError('Competition layout changed')
                coverage,candidates=totals.collect(snapshot,base,saved)
                if cursor is not None and coverage['source_state']!='available':
                    raise ValueError('Competition source changed; start a fresh ranking')
                ranking=(totals.rank(candidates,sort_by,order,minutes_over,limit)
                         if coverage['source_state']=='available' else None)
                pin=None;offset=0
                if ranking is not None:
                    pin=hashlib.sha256(json.dumps({'process':(process.pid,process.started),
                        'save':self._public_save(save),'tables':tables,'source':coverage,
                        'candidates':[(c['person_index'],c['source_ordinal'],c['_raw_hex'],c['_identity'])
                                      for c in candidates]},sort_keys=True,ensure_ascii=True).encode()).hexdigest()
                if cursor is not None:
                    continuation=self.database_cursors.get(cursor)
                    if (not continuation or continuation.get('kind')!='league_player_ranking'
                            or continuation['criteria']!=criteria or continuation['source_pin']!=source_pin
                            or pin!=source_pin):
                        raise ValueError('Ranking cursor expired or source/filter changed; start a fresh ranking')
                    offset=continuation['offset']
                selected=[] if ranking is None else ranking['rows']
                unknown=[] if ranking is None else ranking['unknown_rows']
                combined=[('ranked',r)for r in selected]+[('unknown',r)for r in unknown]
                page=combined[offset:offset+page_size];end=offset+len(page)
                rows=[];unknown_rows=[];pending=[]
                for kind,candidate in page:
                    if kind=='unknown':unknown_rows.append(candidate);continue
                    identity=candidate['_identity'];person=None;binding=None
                    if identity is not None:
                        native=identity['native_identity']
                        person={'database_index':native['database_index'],'native_id':native['native_id'],
                                'secondary_id':native['native_id']if native['random_id']is None else native['random_id'],
                                'record_kind':identity['record_kind'],'name':None,'display_name':None}
                        if identity['record_kind']in('actual','player_staff'):
                            decoded,token=self._roster_player(snapshot,candidate['_primary_address'],tables,
                                                            False,{},profile_policy='available')
                            if decoded['native_identity']!=native:raise ValueError('Ranked player identity changed')
                            person.update(name=decoded['name'],display_name=decoded['display_name'])
                            binding=self._player_binding(candidate['_primary_address'],decoded,token,tables,'available')
                    rows.append({key:candidate[key]for key in ('rank','person_index','starting_appearances',
                        'minutes','goals','metric_states','raw','last_associated_team_index','last_associated_team')})
                    rows[-1].update(person=person,player_ref=None,identity_state=candidate['identity_state'],
                                    source_row_index=candidate['source_ordinal'])
                    pending.append(binding)
                meta=None if ranking is None else {key:value for key,value in ranking.items()if key not in('rows','unknown_rows')}
                result={'session_id':session_id,'observed_at':datetime.now(timezone.utc).isoformat(),
                        'save':self._public_save(save),'competition_ref':competition_ref,
                        'source':coverage,'ranking':meta,'rows':rows,'unknown_rows':unknown_rows,
                        'source_pin':pin,'cursor':cursor,'next_cursor':None,'page_offset':offset,
                        'page_size':page_size,'returned_count':len(rows),'returned_unknown_count':len(unknown_rows),
                        'returned_ranked_rows_complete':ranking is not None and end>=len(selected),
                        'returned_complete':ranking is not None and end==len(combined),
                        'complete_resident_counter_ranking':ranking is not None and not unknown,
                        'all_source_actor_identities_available':coverage.get('unknown_identity_count')==0 and coverage.get('unsupported_player_profile_count')==0,
                        'scope':'current COMP-owned counter population; not a reconstructed fixture lineup',
                        'limitations':totals.SCOPE}
                if len(json.dumps(result,ensure_ascii=True).encode())>2*1024*1024:
                    raise ValueError('Ranking page exceeds response budget')
                snapshot.verify();self._current(session_id)
            except (ValueError,IndexError,KeyError,TypeError,BridgeError) as exc:
                raise BridgeError(f'League player ranking rejected; no partial result returned: {exc}') from exc
            if len(self.player_refs)+sum(p is not None for p in pending)>1000:self.player_refs.clear()
            for row,binding in zip(rows,pending,strict=True):
                if binding is not None:
                    ref=secrets.token_urlsafe(12);self.player_refs[ref]=binding;row['player_ref']=ref
            if ranking is not None and end<len(combined):
                if len(self.database_cursors)>=100:self.database_cursors.clear()
                ref=secrets.token_urlsafe(12)
                self.database_cursors[ref]={'kind':'league_player_ranking','criteria':criteria,
                                            'source_pin':pin,'offset':end}
                result['next_cursor']=ref
            return result

    def get_league_scorers(self, session_id: str, competition_ref: str, limit: int = 10) -> dict:
        """Rank every resident competition PERSON goal counter before publishing refs."""
        integer(limit, 1, 50, 'limit')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            if not isinstance(competition_ref, str) or competition_ref not in self.competition_refs:
                raise BridgeError('Unknown competition reference. Call fm_find_competitions again.')
            saved = self.competition_refs[competition_ref]
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            pending = []
            try:
                if saved['tables'] != tables:
                    raise ValueError('Competition runtime layout changed')
                coverage, candidates = competition_scorers.collect(snapshot, base, saved)
                ranking = league_scorers.rank_candidates(candidates, limit) if coverage['source_state'] == 'available' else None
                rows = []
                team_cache = {}
                if ranking is not None:
                    for candidate in ranking['rows']:
                        identity = candidate['_identity']
                        person = None
                        binding = None
                        if identity is not None:
                            native = identity['native_identity']
                            person = {
                                'database_index': native['database_index'],
                                'native_id': native['native_id'],
                                'secondary_id': native['native_id'] if native['random_id'] is None else native['random_id'],
                                'record_kind': identity['record_kind'],
                                'name': None,
                                'display_name': None,
                            }
                            if identity['record_kind'] in ('actual', 'player_staff'):
                                decoded, token = self._roster_player(
                                    snapshot, candidate['_primary_address'], tables, False, {},
                                    profile_policy='available',
                                )
                                if decoded['native_identity'] != native:
                                    raise ValueError('Ranked scorer identity changed')
                                person.update(name=decoded['name'], display_name=decoded['display_name'])
                                binding = self._player_binding(
                                    candidate['_primary_address'], decoded, token, tables, 'available',
                                )
                        team_index = candidate['last_associated_team_index']
                        last_team = None
                        team_state = 'null_reference'
                        if team_index is not None:
                            if team_index not in team_cache:
                                team_info = database.table(snapshot, base, 'teams')
                                team_cache[team_index] = (teams.by_index(snapshot, base, team_index)[0]
                                                          if team_index < team_info['count'] else None)
                            last_team = team_cache[team_index]
                            team_state = 'canonical_team' if last_team is not None else 'unresolved_reference'
                        rows.append({
                            'rank': candidate['rank'], 'goals': candidate['goals'],
                            'person_index': candidate['person_index'], 'person': person,
                            'identity_state': candidate['identity_state'], 'player_ref': None,
                            'source_row_index': candidate['source_ordinal'],
                            'last_associated_team_index': team_index,
                            'last_associated_team': last_team, 'last_team_state': team_state,
                        })
                        pending.append(binding)
                result = {
                    'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'as_of_date': save['current_date'],
                    'as_of_calendar_year': int(save['current_date'][:4]),
                    'competition_ref': competition_ref, 'source': coverage,
                    'ranking': None if ranking is None else {key: value for key, value in ranking.items() if key != 'rows'},
                    'rows': rows, 'limit': limit,
                    'complete_resident_counter_ranking': ranking is not None,
                    'all_ranked_player_profiles_available': all(binding is not None for binding in pending) if ranking is not None else False,
                    'season_scope': 'current runtime competition stats object; native season discriminator reported',
                    'universal_season_rollover_semantics': 'not_established',
                    'award_eligibility_state': 'not_evaluated',
                    'evidence': 'canonical_COMP_to_owned_resident_PERSON_cumulative_goal_counter',
                    'limitations': 'Stored individual goals across the complete observed resident competition pool. '
                        'No assists or minutes prefilter. Cutoff ties are complete; equal goals have no award tiebreak. '
                        'The last associated TEAM is not attribution of every goal to that club. '
                        'Native capture filters and unrefreshed resident data limit coverage; wider historical and award '
                        'coverage are not established. Missing tables remain unavailable. Non-atomic reads with '
                        'consumed-byte, runtime ownership, identity and process rechecks; no native sort or refresh.',
                }
                if len(json.dumps(result, ensure_ascii=True).encode()) + 20 * len(pending) > 2 * 1024 * 1024:
                    raise ValueError('Complete scorer result exceeds response budget; no partial tie returned')
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
                raise BridgeError(f'League scorers rejected; no partial ranking returned: {exc}') from exc
            if len(self.player_refs) + sum(binding is not None for binding in pending) > 1000:
                self.player_refs.clear()
            for row, binding in zip(rows, pending, strict=True):
                if binding is not None:
                    reference = secrets.token_urlsafe(12)
                    self.player_refs[reference] = binding
                    row['player_ref'] = reference
            return result

    def get_competition(self, session_id: str, competition_ref: str) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            if not isinstance(competition_ref, str) or competition_ref not in self.competition_refs:
                raise BridgeError('Unknown competition reference. Call fm_find_competitions again.')
            saved = self.competition_refs[competition_ref]
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                if saved['tables'] != tables:
                    raise ValueError('Competition runtime layout changed')
                info = database.table(snapshot, base, 'competitions')
                row = competitions.by_index(snapshot, base, saved['database_index'], include_context=True)
                address = world.pointer(snapshot, info['start'] + saved['database_index'] * 8)
                if address != saved['address'] or (row['native_id'], row['random_id']) != (saved['native_id'], saved.get('random_id')):
                    raise ValueError('Competition identity or membership changed')
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                self.competition_refs.pop(competition_ref, None)
                raise BridgeError(f'Competition reference rejected: {exc}') from exc
            self._current(session_id)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': self._public_save(save), 'competition': {**row, 'competition_ref': competition_ref},
                'save_identity': 'native_binding_rechecked',
                'evidence': 'rechecked_competition_identity_membership_and_stored_names',
                'limitations': competitions.SCOPE}

    def get_competition_stages(self, session_id: str, competition_ref: str) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            if not isinstance(competition_ref, str) or competition_ref not in self.competition_refs:
                raise BridgeError('Unknown competition reference. Call fm_find_competitions again.')
            saved = self.competition_refs[competition_ref]
            tables = self._player_layout(process)
            snapshot, save, _ = self._world_state(process, tables)
            try:
                if saved['tables'] != tables:
                    raise ValueError('Competition runtime layout changed')
                context, pending = competition_stages.catalog(snapshot, tables[0]-players.RVA[0], saved)
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Competition stages rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            if len(self.stage_refs)+len(pending) > 10000:
                self.stage_refs.clear()
            results = []
            for row, binding in pending:
                ref = None
                if binding is not None:
                    ref = secrets.token_urlsafe(12)
                    self.stage_refs[ref] = {'competition': dict(saved), 'binding': binding}
                results.append({**row, 'stage_ref': ref})
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), **context,
                    'competition': {**context['competition'], 'competition_ref': competition_ref},
                    'stages': results, 'count': len(results),
                    'league_table_count': sum(row['standings_available'] for row in results),
                    'coverage': 'top_level_stages_and_group_league_children',
                    'evidence': 'rechecked_runtime_stage_vectors_and_owner_membership',
                    'limitations': competition_stages.SCOPE}

    def get_standings(self, session_id: str, stage_ref: str) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.stage_refs.get(stage_ref) if isinstance(stage_ref, str) else None
            if saved is None:
                raise BridgeError('Unknown or expired stage reference. Call fm_get_competition_stages again.')
            tables = self._player_layout(process)
            snapshot, save, _ = self._world_state(process, tables)
            try:
                if saved['competition']['tables'] != tables:
                    raise ValueError('Competition runtime layout changed')
                base = tables[0]-players.RVA[0]
                context, stages = competition_stages.catalog(snapshot, base, saved['competition'])
                match = next(((row, binding) for row, binding in stages if binding == saved['binding']), None)
                if match is None:
                    raise ValueError('Stage identity or membership changed; obtain a fresh stage reference')
                stage, binding = match
                summary, pending = competition_stages.standings(snapshot, base, binding)
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Standings rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            if len(self.team_refs)+len(pending) > 10000:
                self.team_refs.clear()
            results = []
            for row, team_binding in pending:
                if team_binding is not None:
                    ref = secrets.token_urlsafe(12)
                    team = row['team']
                    self.team_refs[ref] = {**team_binding, 'tables': tables, 'source': 'competition',
                                           'label': f"{team['kind']} type {team['native_type_code']}"}
                    row = {**row, 'team': {**team, 'team_ref': ref}}
                results.append(row)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), **context, **summary,
                    'stage': {**stage, 'stage_ref': stage_ref}, 'rows': results,
                    'evidence': 'rechecked_native_league_rows_positions_and_team_membership',
                    'limitations': competition_stages.TABLE_SCOPE}

    def get_fixture_coverage(self, session_id: str) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            snapshot, save, _ = self._world_state(process, tables)
            try:
                catalog, _, _ = fixtures.catalog(snapshot, tables[0]-players.RVA[0])
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Fixture coverage rejected: {exc}') from exc
            self._current(session_id)
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), **catalog,
                    'evidence': 'typed_resident_fixture_managers_and_materialization_flags',
                    'limitations': fixtures.SCOPE}

    def _publish_fixture(self, row, team_bindings, competition_address, binding, tables, current_date,
                         ref=None, stage_binding=None, stadium_binding=None):
        row = dict(row)
        if stadium_binding is not None:
            row['stadium'] = self._publish_stadium(row['stadium'], stadium_binding, tables)
        row['days_from_current_date'] = (date.fromisoformat(row['date']) - date.fromisoformat(current_date)).days
        for field, team_binding in zip(('home_team', 'away_team'), team_bindings):
            if team_binding is None:
                continue
            team = row[field]
            team_ref = secrets.token_urlsafe(12)
            self.team_refs[team_ref] = {**team_binding, 'tables': tables, 'source': 'competition',
                                      'label': f"{team['kind']} type {team['native_type_code']}"}
            row[field] = {**team, 'team_ref': team_ref}
        if row['competition'] is not None:
            competition = row['competition']
            competition_ref = secrets.token_urlsafe(12)
            self.competition_refs[competition_ref] = {'address': competition_address,
                'native_id': competition['native_id'], 'random_id': competition['random_id'], 'database_index': competition['database_index'],
                'tables': tables}
            row['competition'] = {**competition, 'competition_ref': competition_ref}
            if stage_binding is not None:
                stage_ref = secrets.token_urlsafe(12)
                self.stage_refs[stage_ref] = {'competition': dict(self.competition_refs[competition_ref]),
                                              'binding': stage_binding}
                row['stage_link'] = {**row['stage_link'], 'stage': {
                    **row['stage_link']['stage'], 'stage_ref': stage_ref}}
        ref = ref or secrets.token_urlsafe(12)
        self.fixture_refs[ref] = {**binding, 'tables': tables}
        return {**row, 'fixture_ref': ref}

    def find_fixtures(self, session_id: str, year: int | None = None,
                      team_native_id: int | None = None, competition_native_id: int | None = None,
                      date_from: str | None = None, date_to: str | None = None,
                      record_kind: str | None = None, max_matches: int = 20,
                      record_budget: int = 1000, bucket_budget: int = 4096,
                      cursor: str | None = None, include_stage: bool = False, selector_prefilter: bool = False) -> dict:
        if type(selector_prefilter) is not bool:
            raise BridgeError('selector_prefilter must be a boolean.')
        if type(include_stage) is not bool:
            raise BridgeError('include_stage must be a boolean.')
        integer(max_matches, 1, 100, 'max_matches')
        integer(record_budget, 1, 1000, 'record_budget')
        integer(bucket_budget, 1, 4096, 'bucket_budget')
        if year is not None:
            integer(year, 1, 9999, 'year')
        for label, value in (('team_native_id', team_native_id), ('competition_native_id', competition_native_id)):
            if value is not None:
                integer(value, 1, 0xFFFFFFFF, label)
        if record_kind is not None and record_kind not in ('fixture', 'result'):
            raise BridgeError('record_kind must be fixture or result.')
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise BridgeError('Fixture cursor must be a nonempty string.')
        criteria = dict(year=year, team_native_id=team_native_id, competition_native_id=competition_native_id,
                        date_from=date_from, date_to=date_to, record_kind=record_kind, include_stage=include_stage, selector_prefilter=selector_prefilter)
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            tables = self._player_layout(process)
            base = tables[0]-players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                catalog, years, identity = fixtures.catalog(snapshot, base)
                selected_year = catalog['main_year'] if year is None else year
                if selected_year not in years:
                    raise ValueError('Year has no resident fixture manager; call fm_get_fixture_coverage')
                bounds = fixtures.date_bounds(selected_year, date_from, date_to)
                position, bucket_identity = (bounds[0], 0, 0), None
                if cursor is not None:
                    saved = self.database_cursors.get(cursor)
                    if (not saved or saved['kind'] != 'fixtures' or saved['criteria'] != criteria
                            or saved['identity'] != identity):
                        raise ValueError('Fixture cursor expired or belongs to a different query')
                    position, bucket_identity = saved['position'], saved['bucket_identity']
                pending, progress = fixtures.scan(snapshot, base, years[selected_year], selected_year, bounds,
                    team_native_id, competition_native_id, record_kind, position, bucket_identity,
                    max_matches, record_budget, bucket_budget, include_stage, selector_prefilter)
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Fixture query rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            if len(self.fixture_refs)+len(pending) > 10000:
                self.fixture_refs.clear()
            if len(self.team_refs)+2*len(pending) > 10000:
                self.team_refs.clear()
            if len(self.competition_refs)+len(pending) > 10000:
                self.competition_refs.clear()
            if len(self.stage_refs)+sum(stage_binding is not None for _, _, _, stage_binding, _, _ in pending) > 10000:
                self.stage_refs.clear()
            if len(self.stadium_refs)+len(pending) > 10000:
                self.stadium_refs.clear()
            results = [self._publish_fixture(row, team_bindings, comp_address,
                       {**binding, 'catalog_identity': identity}, tables, save['current_date'], stage_binding=stage_binding, stadium_binding=stadium_binding)
                       for row, team_bindings, comp_address, stage_binding, stadium_binding, binding in pending]
            next_cursor = None
            if not progress['finished']:
                if len(self.database_cursors) >= 100:
                    self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = {'kind': 'fixtures', 'criteria': criteria,
                    'identity': identity, 'position': progress['position'],
                    'bucket_identity': progress['bucket_identity']}
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'year': selected_year, 'criteria': criteria,
                    'coverage': years[selected_year]['coverage'], 'fixtures': results, 'count': len(results),
                    'scanned_records': progress['scanned_records'], 'examined_buckets': progress['examined_buckets'],
                    'next_cursor': next_cursor, 'stop_reason': progress['stop_reason'],
                    'reached_resident_range_end': progress['finished'],
                    'ordering': 'calendar_day_then_native_group_and_slot',
                    'evidence': 'rechecked_resident_fixture_buckets_dates_scores_and_database_links',
                    'limitations': fixtures.SCOPE}

    def get_fixture_rules(self, session_id: str, fixture_ref: str) -> dict:
        from . import fixture_rules
        if not isinstance(fixture_ref, str) or not fixture_ref:
            raise BridgeError('fixture_ref must be a nonempty string from fm_find_fixtures.')
        with self.lock, self._read_scope(session_id):
            try:
                return fixture_rules.collect(self, session_id, fixture_ref)
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                self.fixture_refs.pop(fixture_ref, None)
                raise BridgeError(f'Fixture rules rejected; no partial result returned: {exc}') from exc

    def get_fixture(self, session_id: str, fixture_ref: str, include_stage: bool = False) -> dict:
        if type(include_stage) is not bool:
            raise BridgeError('include_stage must be a boolean.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.fixture_refs.get(fixture_ref) if isinstance(fixture_ref, str) else None
            if saved is None:
                raise BridgeError('Unknown or expired fixture reference. Call fm_find_fixtures again.')
            tables = self._player_layout(process)
            snapshot, save, _ = self._world_state(process, tables)
            base = tables[0]-players.RVA[0]
            try:
                if saved['tables'] != tables:
                    raise ValueError('Fixture runtime layout changed')
                _, years, identity = fixtures.catalog(snapshot, base)
                if saved['catalog_identity'] != identity:
                    raise ValueError('Resident fixture inventory changed')
                binding = years[saved['year']]
                entries, route = fixtures.bucket(snapshot, binding, saved['day'], saved['group'])
                if (route != saved['route'] or saved['slot'] >= len(entries)
                        or entries[saved['slot']] != saved['address']):
                    raise ValueError('Fixture bucket membership changed')
                cache = {}
                decoded = fixtures.record(snapshot, base, saved['address'], saved['year'], saved['day'], cache)
                if decoded['identity'] != saved['identity']:
                    raise ValueError('Fixture identity changed')
                row, team_bindings, stage_binding = fixtures.detail(
                    snapshot, base, saved['address'], saved['year'], saved['day'], decoded, cache, include_stage)
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                self.fixture_refs.pop(fixture_ref, None)
                raise BridgeError(f'Fixture reference rejected: {exc}') from exc
            self._current(session_id)
            if len(self.team_refs)+2 > 10000:
                self.team_refs.clear()
            if len(self.competition_refs)+1 > 10000:
                self.competition_refs.clear()
            if stage_binding is not None and len(self.stage_refs) >= 10000:
                self.stage_refs.clear()
            if decoded['stadium_binding'] is not None and len(self.stadium_refs) >= 10000:
                self.stadium_refs.clear()
            row = self._publish_fixture(row, team_bindings, decoded['competition_address'], saved, tables,
                                        save['current_date'], fixture_ref, stage_binding=stage_binding, stadium_binding=decoded['stadium_binding'])
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(save), 'fixture': row,
                    'evidence': 'rechecked_fixture_identity_bucket_and_database_membership',
                    'limitations': fixtures.SCOPE}

    def get_competition_registrations(self, session_id: str, competition_ref: str,
                                      year: int | None = None, max_matches: int = 100,
                                      record_budget: int = 1000, cursor: str | None = None) -> dict:
        integer(max_matches, 1, 100, 'max_matches')
        integer(record_budget, 1, 1000, 'record_budget')
        if year is not None:
            integer(year, 1, 65534, 'year')
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise BridgeError('Competition registration cursor must be a nonempty string.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            if not isinstance(competition_ref, str) or competition_ref not in self.competition_refs:
                raise BridgeError('Unknown competition reference. Call fm_find_competitions again.')
            saved = self.competition_refs[competition_ref]
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                if saved['tables'] != tables:
                    raise ValueError('Competition runtime layout changed')
                comp_info = database.table(snapshot, base, 'competitions')
                competition = competitions.by_index(snapshot, base, saved['database_index'], include_context=True)
                address = world.pointer(snapshot, comp_info['start'] + saved['database_index']*8)
                if address != saved['address'] or (competition['native_id'], competition['random_id']) != (saved['native_id'], saved.get('random_id')):
                    raise ValueError('Competition identity or membership changed')
                info = competition_registrations.vector(snapshot, address)
                team_info = teams.lookup(snapshot, base)
                identity = (info['identity'], team_info['identity'], team_info['lookup_identity'])
                criteria = {'competition_ref': competition_ref, 'year': year}
                start = 0
                if cursor is not None:
                    previous = self.database_cursors.get(cursor)
                    if (not previous or previous['kind'] != 'competition_registrations'
                            or previous['identity'] != identity or previous.get('criteria') != criteria):
                        raise ValueError('Competition registration cursor expired or belongs to a different query')
                    start = previous['index']
                end, pending, null_slots = start, [], 0
                while end < min(info['count'], start + record_budget):
                    pointer = players.u64(snapshot(info['start'] + end*8, 8))
                    index = end
                    end += 1
                    if not pointer:
                        null_slots += 1
                        continue
                    if year is not None and competition_registrations.fields(snapshot, pointer)[1] != year:
                        continue
                    row, binding = competition_registrations.record(snapshot, base, pointer, team_info=team_info)
                    pending.append(({'registration_index': index, **row}, binding))
                    if len(pending) == max_matches:
                        break
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Competition registrations rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            if len(self.team_refs) + sum(binding is not None for _, binding in pending) > 10000:
                self.team_refs.clear()
            results = []
            for row, binding in pending:
                if binding is not None:
                    ref = secrets.token_urlsafe(12)
                    team = row['team']
                    self.team_refs[ref] = {**binding, 'tables': tables, 'source': 'competition',
                                          'label': f"{team['kind']} type {team['native_type_code']}"}
                    row = {**row, 'team': {**team, 'team_ref': ref}}
                results.append(row)
            next_cursor = None
            if end < info['count']:
                if len(self.database_cursors) >= 100:
                    self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = {'kind': 'competition_registrations', 'criteria': criteria,
                    'identity': identity, 'index': end}
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': self._public_save(save), 'competition': {**competition, 'competition_ref': competition_ref},
                'year_filter': year, 'registrations': results, 'count': len(results),
                'total_registration_slots': info['count'], 'scanned_slots': end-start,
                'null_record_slots': null_slots, 'start_index': start, 'next_index': end,
                'next_cursor': next_cursor, 'complete_native_list': start == 0 and end == info['count'],
                'stop_reason': 'list_end' if end == info['count'] else
                               'match_limit' if len(pending) == max_matches else 'record_budget',
                'ordering': 'native_registration_slot', 'evidence': 'rechecked_competition_registration_vector',
                'limitations': competition_registrations.SCOPE}

    def get_competition_teams(self, session_id: str, competition_ref: str,
                              assignment: str = 'current', max_matches: int = 100,
                              record_budget: int = 200000, cursor: str | None = None) -> dict:
        integer(max_matches, 1, 100, 'max_matches')
        integer(record_budget, 1, 200000, 'record_budget')
        if not isinstance(assignment, str) or assignment not in teams.ASSIGNMENTS:
            raise BridgeError('assignment must be current, next, secondary or next_secondary.')
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise BridgeError('Team assignment cursor must be a nonempty string.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            if not isinstance(competition_ref, str) or competition_ref not in self.competition_refs:
                raise BridgeError('Unknown competition reference. Call fm_find_competitions again.')
            saved = self.competition_refs[competition_ref]
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, save, _ = self._world_state(process, tables)
            try:
                if saved['tables'] != tables:
                    raise ValueError('Competition runtime layout changed')
                comp_info = database.table(snapshot, base, 'competitions')
                competition = competitions.by_index(snapshot, base, saved['database_index'], include_context=True)
                comp_address = world.pointer(snapshot, comp_info['start'] + saved['database_index']*8)
                if comp_address != saved['address'] or (competition['native_id'], competition['random_id']) != (saved['native_id'], saved.get('random_id')):
                    raise ValueError('Competition identity or membership changed')
                info = teams.lookup(snapshot, base)
                criteria = {'competition_ref': competition_ref, 'assignment': assignment}
                identity = (info['identity'], info['lookup_identity'])
                start = 0
                if cursor is not None:
                    previous = self.database_cursors.get(cursor)
                    if (not previous or previous['kind'] != 'competition_teams'
                            or previous['identity'] != identity or previous.get('criteria') != criteria):
                        raise ValueError('Team assignment cursor expired or belongs to a different query')
                    start = previous['index']
                native = self._run('scan-team-index', process,
                    '--list-header', str(info['header']), '--list-start', str(info['start']),
                    '--list-count', str(info['count']), '--lookup-header', str(info['lookup_header']),
                    '--start-index', str(start), '--record-budget', str(record_budget),
                    '--max-matches', str(max_matches), '--team-primary', str(base + world.TYPES['team'][0]),
                    '--national-team-primary', str(base + world.TYPES['national_team'][0]),
                    '--competition', str(comp_address), '--team-assignment', assignment)
                end, matches, reason = native.get('next_index'), native.get('matches'), native.get('stop_reason')
                if (type(end) is not int or not start <= end <= min(info['count'], start + record_budget)
                        or not isinstance(matches, list) or len(matches) > max_matches
                        or type(native.get('scanned_records')) is not int or native['scanned_records'] != end-start
                        or (end == start and start < info['count'])
                        or reason not in ('table_end', 'record_budget', 'match_limit')
                        or (reason == 'table_end') != (end == info['count'])
                        or (reason == 'match_limit' and len(matches) != max_matches)
                        or (reason == 'record_budget' and end-start != record_budget)):
                    raise ValueError('Invalid native team scan receipt')
                actual, national, unavailable = (native.get(key) for key in
                    ('teams_examined', 'national_teams_examined', 'lookup_unavailable_records'))
                if (any(type(value) is not int for value in (actual, national, unavailable))
                        or min(actual, national, unavailable) < 0 or actual + unavailable != end-start
                        or not len(matches) <= actual or national > actual
                        or unavailable != max(0, end-max(start, info['lookup_count']))):
                    raise ValueError('Native team scan counts disagree')
                pending, last_index = [], start - 1
                for hit in matches:
                    index = hit['database_index']
                    if type(index) is not int or not last_index < index < end:
                        raise ValueError('Native team result index is duplicated, unordered or outside the scanned range')
                    last_index = index
                    row, binding = teams.by_index(snapshot, base, index, info=info)
                    if binding['address'] != int(hit['address'], 16):
                        raise ValueError('Team table membership changed')
                    selected, fallback = teams.selection(snapshot, binding['address'], assignment)
                    if selected != comp_address or (assignment == 'current' and not binding['owner_address']):
                        raise ValueError('Team competition assignment changed')
                    row['used_current_assignment_fallback'] = fallback
                    pending.append((row, binding))
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Competition teams rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            if len(self.team_refs) + len(pending) > 10000:
                self.team_refs.clear()
            results = []
            for row, binding in pending:
                ref = secrets.token_urlsafe(12)
                self.team_refs[ref] = {**binding, 'tables': tables, 'source': 'competition',
                                      'label': f"{row['kind']} type {row['native_type_code']}"}
                results.append({**row, 'team_ref': ref})
            next_cursor = None
            if end < info['count']:
                if len(self.database_cursors) >= 100:
                    self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = {'kind': 'competition_teams', 'criteria': criteria,
                    'identity': identity, 'index': end}
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'save': self._public_save(save), 'competition': {**competition, 'competition_ref': competition_ref},
                'assignment': assignment, 'teams': results, 'count': len(results),
                'total_team_records': info['count'], 'selected_lookup_records': info['lookup_count'],
                'scanned_records': end-start, 'teams_examined': actual, 'national_teams_examined': national,
                'lookup_unavailable_records': unavailable, 'start_index': start, 'next_index': end,
                'next_cursor': next_cursor, 'stop_reason': reason,
                'complete_table_scan': start == 0 and end == info['count'],
                'ordering': 'native_database_index', 'evidence': 'rechecked_native_direct_team_assignments',
                'limitations': teams.SCOPE}

    def query_save_players(self, session_id: str, minimum_attributes: dict | None = None,
                           maximum_attributes: dict | None = None, minimum_profile: dict | None = None,
                           maximum_profile: dict | None = None, born_on_or_after: str | None = None,
                           born_on_or_before: str | None = None, name_contains: str | None = None,
                           max_matches: int = 20, record_budget: int = 200000, cursor: str | None = None) -> dict:
        try:
            filters = recruitment.compile_filters(minimum_attributes, maximum_attributes, minimum_profile,
                maximum_profile, born_on_or_after, born_on_or_before)
        except (ValueError, TypeError) as exc:
            raise BridgeError(f'Invalid recruitment criteria: {exc}') from exc
        return self._find_database_records(session_id, 'recruitment', '' if name_contains is None else name_contains,
                                           max_matches, record_budget, cursor, filters)

    def _find_database_records(self, session_id, kind, name, max_matches, record_budget, cursor, filters=None):
        clubs = kind == 'clubs'
        staff_search = kind == 'staff'
        recruitment_search = kind == 'recruitment'
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            integer(max_matches, 1, 100, 'max_matches')
            integer(record_budget, 1, 200000, 'record_budget')
            if (not isinstance(name, str) or (not 3 <= len(name) <= 128 and not (recruitment_search and name == ''))
                    or any(ord(c) < 32 or ord(c) == 127 for c in name)):
                raise BridgeError('Search name must contain 3–128 characters and no controls.')
            try:
                encoded = name.encode('utf-8')
            except UnicodeError as exc:
                raise BridgeError('Search name must be valid Unicode.') from exc
            if len(encoded) > 128:
                raise BridgeError('Search name must fit within 128 UTF-8 bytes.')
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, record, _ = self._world_state(process, tables)
            try:
                info = database.table(snapshot, base, 'people' if staff_search or recruitment_search else kind)
                start = 0
                if cursor is not None and (not isinstance(cursor, str) or not cursor):
                    raise BridgeError('Search cursor must be a nonempty string.')
                if cursor is not None:
                    saved = self.database_cursors.get(cursor)
                    if not saved or saved['name'] != name or saved['kind'] != kind or saved['identity'] != info['identity']:
                        raise ValueError('Entity table cursor expired or belongs to a different query')
                    if recruitment_search and saved.get('criteria') != filters['criteria']:
                        raise ValueError('Recruitment cursor belongs to different criteria')
                    start = saved['index']
                if recruitment_search:
                    for layout in (players.RVA, players.STAFF_RVA):
                        player_profile.verify_getters(snapshot, base, base + layout[0])
                        personality.verify_getters(snapshot, base, base + layout[2])
                command = 'scan-club-index' if clubs else 'scan-staff-index' if staff_search else 'scan-player-index'
                primary = base + world.TYPES['club'][0] if clubs else base + staff.LAYOUTS['staff'][0] if staff_search else tables[0]
                person_table = base + staff.LAYOUTS['staff'][1] if staff_search else tables[2]
                native = self._run(command, process,
                                   '--list-header', str(info['header']), '--list-start', str(info['start']),
                                   '--list-count', str(info['count']), '--start-index', str(start),
                                   '--record-budget', str(record_budget), '--max-matches', str(max_matches),
                                   '--player-primary', str(primary), '--player-playing', str(tables[1]),
                                   '--player-person', str(person_table), '--player-query', name,
                                   '--player-staff-primary', str(base + players.STAFF_RVA[0]),
                                   '--player-staff-person', str(base + players.STAFF_RVA[2]),
                                   '--human-primary', str(base + staff.LAYOUTS['human_manager'][0]),
                                   '--human-person', str(base + staff.LAYOUTS['human_manager'][1]),
                                   *(['--query-players', *filters['native']] if recruitment_search else []))
                end = native.get('next_index')
                matches = native.get('matches')
                reason = native.get('stop_reason')
                if (type(end) is not int or not start <= end <= min(info['count'], start + record_budget)
                        or not isinstance(matches, list) or len(matches) > max_matches
                        or native.get('scanned_records') != end - start
                        or (end == start and start < info['count'])
                        or reason not in ('table_end', 'record_budget', 'match_limit')
                        or (reason == 'table_end') != (end == info['count'])
                        or (reason == 'match_limit' and len(matches) != max_matches)
                        or (reason == 'record_budget' and end - start != record_budget)):
                    raise ValueError('Invalid native table scan receipt')
                actual_key = 'clubs_examined' if clubs else 'staff_examined' if staff_search else 'actual_players_examined'
                other_key = 'other_club_records' if clubs else 'other_person_records'
                actual, other = native.get(actual_key), native.get(other_key)
                if (type(actual) is not int or type(other) is not int or min(actual, other) < 0
                        or actual + other != end - start):
                    raise ValueError('Native record type counts disagree')
                staff_examined = native.get('player_staff_examined', 0)
                if type(staff_examined) is not int or not 0 <= staff_examined <= actual:
                    raise ValueError('Native player/staff count disagrees')
                unavailable = native.get('unavailable_name_records', 0)
                if type(unavailable) is not int or not 0 <= unavailable <= actual - len(matches):
                    raise ValueError('Native unavailable name count disagrees')
                pending, indices, classifications = [], set(), {}
                for hit in matches:
                    address = int(hit['address'], 16)
                    index_offset = 8 if clubs else (staff.layout(snapshot, base, address)[1][2] if staff_search
                                                  else players.person_offset(snapshot, address, tables)) + 8
                    index = int.from_bytes(snapshot(address + index_offset, 4), 'little')
                    if not start <= index < end or index in indices:
                        raise ValueError('Native result index is duplicated or outside the scanned range')
                    indices.add(index)
                    if clubs:
                        database.club_membership(snapshot, base, info, index, address)
                        player, identity = world.club(snapshot, base, address)
                    elif staff_search:
                        database.staff_membership(snapshot, base, info, index, address)
                        player, identity = staff.decode(snapshot, base, address)
                    else:
                        database.player_membership(snapshot, base, info, index, address)
                        player, identity = players.decode(snapshot, address, tables, **({'include_profile': True} if recruitment_search else {}))
                        if recruitment_search:
                            state, unknown = recruitment.classify(player, filters)
                            if state == 'nonmatch' or state != hit.get('filter_state'):
                                raise ValueError('Player criteria changed during table scan or native prefilter disagrees')
                            classifications[address] = unknown
                    keys = ('name', 'short_name') if clubs else ('name', 'display_name')
                    if not any(name.lower() in player[k].lower() for k in keys):
                        raise ValueError('Record name changed during table scan')
                    pending.append((address, index, player, identity))
                snapshot.verify()
            except (ValueError, IndexError, KeyError, TypeError) as exc:
                raise BridgeError(f'Live {kind} table query rejected; no partial result returned: {exc}') from exc
            self._current(session_id)
            references = self.club_refs if clubs else self.staff_refs if staff_search else self.player_refs
            ref_key = 'club_ref' if clubs else 'staff_ref' if staff_search else 'player_ref'
            if len(references) + len(pending) > 1000:
                references.clear()
            results, unclassified = [], []
            for address, index, player, identity in pending:
                ref = secrets.token_urlsafe(12)
                references[ref] = {'address': address, 'identity': identity, 'tables': tables,
                                         'world_bound': True, 'database_index': index}
                public = {**player, ref_key: ref}
                if classifications.get(address):
                    unclassified.append({'player': public, 'unavailable_fields': classifications[address]})
                else:
                    results.append(public)
            next_cursor = None
            if end < info['count']:
                if len(self.database_cursors) >= 100:
                    self.database_cursors.clear()
                next_cursor = secrets.token_urlsafe(12)
                self.database_cursors[next_cursor] = {'name': name, 'kind': kind, 'identity': info['identity'], 'index': end}
                if recruitment_search:
                    self.database_cursors[next_cursor]['criteria'] = filters['criteria']
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(record), ('clubs' if clubs else 'staff' if staff_search else 'players'): results, 'count': len(results),
                    ('total_club_records' if clubs else 'total_person_records'): info['count'], 'scanned_records': end - start,
                    actual_key: actual, other_key: other,
                    **({} if clubs else {'player_staff_examined': staff_examined, 'unavailable_name_records': unavailable}),
                    'stop_reason': reason, 'next_cursor': next_cursor,
                    **({'criteria': {'name_contains': name or None, **filters['criteria']},
                        'unclassified_players': unclassified, 'unclassified_count': len(unclassified),
                        'candidate_count': len(pending), 'ordering': 'native_database_index',
                        'globally_ranked': False} if recruitment_search else {}),
                    'complete_table_scan': start == 0 and end == info['count'],
                    'evidence': 'save_bound_native_table_with_rechecked_record_membership',
                    'limitations': ('Filters regular and combined player/staff records by stored unmasked ratings and optional birth-date bounds. Results are in database order, not a global ranking. Unknown required fixed potential appears separately and counts toward max_matches. Virtual, retired and staff-only types are counted but not searched. Matching records without any readable name are counted as unavailable_name_records. Current age, price, interest, availability and scouting visibility are not inferred. ' if recruitment_search else 'Searches ordinary CLUB records by full or short name. Other club types, including league bodies, are counted but not searched. ' if clubs else 'Searches staff-only, human-manager and player/staff records. Other person types are counted but not searched. Records with no name are counted as unavailable_name_records. Search results omit jobs and ratings; use fm_get_staff with include_attributes for stored ratings. ' if staff_search else 'Searches regular players and players who also hold staff roles by full or common name. Other types include staff-only, retired and virtual records; they are counted but not searched. Records without any name are counted as unavailable_name_records. ') + 'ASCII matching ignores case; non-ASCII spelling is exact. Reads are non-atomic. Continue every next_cursor to cover a limited scan; an empty page does not prove absence.'}

    def query_team_players(self, session_id: str, team_ref: str,
                           minimum_attributes: dict | None = None, sort_by: str | None = None,
                           limit: int = 20, include_virtual: bool = False,
                           loan_status: str = 'any', minimum_profile: dict | None = None,
                           minimum_health: dict | None = None, maximum_health: dict | None = None,
                           injury_records: str = 'any') -> dict:
        minima = {} if minimum_attributes is None else minimum_attributes
        if not isinstance(minima, dict) or len(minima) > len(players.ATTRIBUTES):
            raise BridgeError('minimum_attributes must map supported attribute names to values from 1 to 20.')
        for name, value in minima.items():
            if name not in players.ATTRIBUTES:
                raise BridgeError(f'Unsupported attribute: {name}')
            integer(value, 1, 20, f'minimum_attributes.{name}')
        profile_minima = {} if minimum_profile is None else minimum_profile
        if not isinstance(profile_minima, dict) or len(profile_minima) > len(player_profile.QUERY_FIELDS):
            raise BridgeError('minimum_profile must map supported profile field paths to numeric minima.')
        for name, value in profile_minima.items():
            if name not in player_profile.QUERY_FIELDS:
                raise BridgeError(f'Unsupported profile field: {name}')
            integer(value, 0, player_profile.QUERY_FIELDS[name], f'minimum_profile.{name}')
        profile_sort = sort_by in player_profile.QUERY_FIELDS if isinstance(sort_by, str) else False
        health_sort = isinstance(sort_by, str) and sort_by in {f'health.{name}' for name in player_health.FIELDS}
        health_minima = {} if minimum_health is None else minimum_health
        health_maxima = {} if maximum_health is None else maximum_health
        for label, bounds in (('minimum_health', health_minima), ('maximum_health', health_maxima)):
            if not isinstance(bounds, dict) or len(bounds) > len(player_health.FIELDS):
                raise BridgeError(f'{label} must map supported health names to native integer bounds.')
            for name, value in bounds.items():
                if name not in player_health.FIELDS:
                    raise BridgeError(f'Unsupported health field: {name}')
                _, lower, upper = player_health.FIELDS[name]
                integer(value, lower, upper, f'{label}.{name}')
        if any(health_minima[k] > health_maxima[k] for k in health_minima.keys() & health_maxima.keys()):
            raise BridgeError('Minimum health bounds must not exceed maximum bounds.')
        if injury_records not in ('any', 'with_records', 'without_records'):
            raise BridgeError('injury_records must be any/with_records/without_records.')
        if sort_by is not None and (not isinstance(sort_by, str) or (sort_by not in players.ATTRIBUTES and not profile_sort and not health_sort)):
            raise BridgeError(f'Unsupported sort attribute: {sort_by}')
        integer(limit, 1, 100, 'limit')
        if type(include_virtual) is not bool or loan_status not in ('any', 'on_loan', 'not_on_loan'):
            raise BridgeError('Use a boolean include_virtual and loan_status any/on_loan/not_on_loan.')
        needs_profile = bool(profile_minima) or profile_sort
        needs_health = bool(health_minima or health_maxima) or health_sort or injury_records != 'any'
        criteria = {'minimum_attributes': minima, 'minimum_profile': profile_minima,
                    'minimum_health': health_minima, 'maximum_health': health_maxima,
                    'include_virtual': include_virtual, 'loan_status': loan_status,
                    'injury_records': injury_records, 'sort_by': sort_by}
        with self.lock:
            previous_refs = set(self.player_refs)
            try:
                roster = self.get_team_squad(session_id, team_ref, include_clubs=loan_status != 'any',
                                             profile_policy='available',
                                             **({'include_profile': True} if needs_profile else {}),
                                             **({'include_health': True} if needs_health else {}))
                if type(roster.get('count')) is not int or roster['count'] != len(roster['players']):
                    raise ValueError('Team query roster population count disagrees with source rows')
                selected = team_player_selection.select(roster['players'], criteria, limit)
                return {'session_id': session_id, 'observed_at': roster['observed_at'],
                        'save': roster['save'], 'club': roster['club'], 'team_ref': team_ref,
                        **({'team': roster['team']} if 'team' in roster else {}),
                        'label': roster['label'], 'roster_count': roster['count'], **selected,
                        'query': {**criteria, 'sort_direction': 'descending' if sort_by else 'name_ascending'},
                        'limitations': 'Filters use native attributes, optional stored profile/health fields and native loan status. '
                            'Known virtual exclusions and failing predicates precede unavailable-value classification; '
                            'all native roster rows are accounted for before limiting matches. '
                            'Completeness covers the included population and does not imply expanded virtual profiles are available. '
                            'Health readings do not trigger a native refresh; injury-record presence does not establish inability to play. '
                            'This does not evaluate roles, match availability, work permits or selection eligibility. ' + roster['limitations']}
            except BaseException as exc:
                for reference in set(self.player_refs) - previous_refs:
                    self.player_refs.pop(reference, None)
                if isinstance(exc, (ValueError, IndexError)):
                    raise BridgeError(f'Team player query rejected; no partial result returned: {exc}') from exc
                raise

    def query_club_staff(self, session_id: str, minimum_attributes: dict | None = None,
                         sort_by: str | None = None, limit: int = 20,
                         coach_name: str | None = None, club_ref: str | None = None,
                         job_contains: str | None = None, minimum_personality: dict | None = None) -> dict:
        minima = {} if minimum_attributes is None else minimum_attributes
        if not isinstance(minima, dict) or len(minima) > len(staff_attributes.QUERY_ATTRIBUTES):
            raise BridgeError('minimum_attributes must map supported staff attributes to values from 1 to 20.')
        for name, value in minima.items():
            if name not in staff_attributes.QUERY_ATTRIBUTES:
                raise BridgeError(f'Unsupported staff attribute: {name}')
            integer(value, 1, 20, f'minimum_attributes.{name}')
        personality_minima = {} if minimum_personality is None else minimum_personality
        if not isinstance(personality_minima, dict) or len(personality_minima) > len(personality.FIELDS):
            raise BridgeError('minimum_personality must map supported personality names to values from 0 to 20.')
        for name, value in personality_minima.items():
            if name not in personality.FIELDS:
                raise BridgeError(f'Unsupported personality rating: {name}')
            integer(value, 0, 20, f'minimum_personality.{name}')
        personality_sort = isinstance(sort_by, str) and sort_by in {f'personality.{name}' for name in personality.FIELDS}
        if sort_by is not None and (not isinstance(sort_by, str) or (sort_by not in staff_attributes.QUERY_ATTRIBUTES and not personality_sort)):
            raise BridgeError(f'Unsupported staff sort attribute: {sort_by}')
        integer(limit, 1, 100, 'limit')
        if job_contains is not None and (not isinstance(job_contains, str) or not 1 <= len(job_contains.strip()) <= 128):
            raise BridgeError('job_contains must be a nonempty title substring of at most 128 characters.')
        job_filter = job_contains.strip().casefold() if job_contains is not None else None
        roster = self.get_club_staff(session_id, coach_name, club_ref, include_attributes=True, include_job=True)
        unmapped = sum(person['contract']['job']['state'] != 'decoded' for person in roster['staff'])
        if job_filter and unmapped:
            raise BridgeError('Job filter rejected: some native job titles are unmapped; no partial matches returned.')
        matches = [person for person in roster['staff']
                   if all(person['attributes'][name] >= value for name, value in minima.items())
                   and all(person['personality'][name] >= value for name, value in personality_minima.items())
                   and (job_filter is None or job_filter in person['contract']['job']['title'].casefold())]
        matches.sort(key=lambda person: (-(person['personality'][sort_by.split('.')[1]] if personality_sort
                                         else person['attributes'][sort_by]) if sort_by else 0,
                                        person['display_name'].casefold(), person['birth_date']))
        return {'session_id': session_id, 'observed_at': roster['observed_at'],
                'save': roster['save'], 'club': roster['club'], 'roster_count': roster['count'],
                'matched_count': len(matches), 'returned_count': min(limit, len(matches)),
                'truncated': len(matches) > limit, 'staff': matches[:limit], 'unmapped_job_count': unmapped,
                'query': {'minimum_attributes': minima, 'minimum_personality': personality_minima,
                          'sort_by': sort_by, 'job_contains': job_contains,
                          'sort_direction': 'descending' if sort_by else 'name_ascending'},
                'limitations': 'Filters underlying stored staff ratings. This does not assess job suitability, availability, coaching workload or coaching stars. ' + roster['limitations']}

    def query_club_staff_wages(self, session_id: str, minimum: int = 0,
                               maximum: int | None = None, limit: int = 20,
                               coach_name: str | None = None, club_ref: str | None = None) -> dict:
        integer(minimum, 0, 2147483647, 'minimum')
        if maximum is not None:
            integer(maximum, minimum, 2147483647, 'maximum')
        integer(limit, 1, 100, 'limit')
        roster = self.get_club_staff(session_id, coach_name, club_ref, include_wage=True)
        matches = [p for p in roster['staff'] if p['contract']['wage']['amount'] >= minimum
                   and (maximum is None or p['contract']['wage']['amount'] <= maximum)]
        matches.sort(key=lambda p: (-p['contract']['wage']['amount'], p['display_name'].casefold(), p['birth_date']))
        return {'session_id': session_id, 'observed_at': roster['observed_at'],
                'save': roster['save'], 'club': roster['club'], 'roster_count': roster['count'],
                'currency': 'GBP', 'period': 'week',
                'roster_contract_wage_sum': sum(p['contract']['wage']['amount'] for p in roster['staff']),
                'matched_contract_wage_sum': sum(p['contract']['wage']['amount'] for p in matches),
                'matched_count': len(matches), 'returned_count': min(limit, len(matches)),
                'truncated': len(matches) > limit, 'staff': matches[:limit],
                'query': {'minimum': minimum, 'maximum': maximum, 'sort_direction': 'wage_descending'},
                'limitations': 'Stored weekly main-contract amounts in GBP. Sums cover only the checked staff list. '
                    'These are not the club wage budget, actual payroll, net pay or total employment cost. '
                    'Bonuses, clauses, contributions and UI currency/period rounding are excluded. ' + roster['limitations']}

    def query_club_staff_contracts(self, session_id: str, expires_on_or_before: str,
                                   limit: int = 100, coach_name: str | None = None,
                                   club_ref: str | None = None) -> dict:
        try:
            cutoff = date.fromisoformat(expires_on_or_before)
            if cutoff.isoformat() != expires_on_or_before or not 1850 <= cutoff.year <= 2200:
                raise ValueError('Noncanonical date')
        except (TypeError, ValueError) as exc:
            raise BridgeError('expires_on_or_before must be YYYY-MM-DD, with year 1850–2200.') from exc
        integer(limit, 1, 100, 'limit')
        roster = self.get_club_staff(session_id, coach_name, club_ref, include_contract_dates=True)
        matches, unclassified = [], []
        fixed_count = 0
        for person in roster['staff']:
            dates = person['contract']['dates']
            if dates['state'] != 'fixed_expiry':
                unclassified.append({'staff_ref': person['staff_ref'], 'display_name': person['display_name'],
                                     'contract_dates': dates})
            else:
                fixed_count += 1
                if dates['expires'] <= expires_on_or_before:
                    matches.append(person)
        matches.sort(key=lambda p: (p['contract']['dates']['expires'], p['display_name'].casefold(), p['birth_date']))
        return {'session_id': session_id, 'observed_at': roster['observed_at'],
                'save': roster['save'], 'club': roster['club'], 'roster_count': roster['count'],
                'fixed_expiry_count': fixed_count, 'unclassified_count': len(unclassified),
                'unclassified_staff': unclassified, 'matched_count': len(matches),
                'returned_count': min(limit, len(matches)), 'truncated': len(matches) > limit,
                'staff': matches[:limit], 'query': {'expires_on_or_before': expires_on_or_before,
                                                  'sort_direction': 'expiry_ascending'},
                'limitations': 'Matches only verified fixed expiries, including already expired dates. '
                    'Unclassified staff are listed separately and are not confirmed nonmatches. '
                    'Does not predict renewals, clauses or departure. ' + roster['limitations']}

    def get_club_staff(self, session_id: str, coach_name: str | None = None,
                       club_ref: str | None = None, include_attributes: bool = False,
                       include_job: bool = False, include_contract_dates: bool = False,
                       include_wage: bool = False, include_contract_status: bool = False,
                       include_contract_bonuses: bool = False, include_contract_terms: bool = False) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            if type(include_contract_terms) is not bool:
                raise BridgeError('include_contract_terms must be a boolean.')
            if type(include_attributes) is not bool:
                raise BridgeError('include_attributes must be a boolean.')
            if type(include_contract_bonuses) is not bool:
                raise BridgeError('include_contract_bonuses must be a boolean.')
            if type(include_job) is not bool:
                raise BridgeError('include_job must be a boolean.')
            if type(include_contract_dates) is not bool:
                raise BridgeError('include_contract_dates must be a boolean.')
            if type(include_contract_status) is not bool:
                raise BridgeError('include_contract_status must be a boolean.')
            if type(include_wage) is not bool:
                raise BridgeError('include_wage must be a boolean.')
            tables = self._player_layout(process)
            base = tables[0] - players.RVA[0]
            snapshot, record, _ = self._world_state(process, tables)
            if club_ref is not None and coach_name is not None:
                raise BridgeError('Select either club_ref or coach_name, not both.')
            if club_ref is None:
                coach = self._select_coach(record, coach_name)
                club_address = world.pointer(snapshot, coach['team_address'] + 0x30)
                club = coach['club']
            else:
                club, club_address, _, _ = self._referenced_club(snapshot, base, club_ref, tables)
            try:
                info = database.table(snapshot, base, 'people')
                currency = wages.base_currency(snapshot, base) if include_wage or include_contract_bonuses or include_contract_terms else None
                addresses, vector_counts, manager_count = set(), [], 0
                for offset in (0x60, 0x78, 0x90):
                    members = world.vector(snapshot, club_address + offset, 512)
                    addresses.update(members)
                    vector_counts.append(len(members))
                for team in world.vector(snapshot, club_address + 0x18, 64):
                    world.typed(snapshot, base, team, 'team')
                    if world.pointer(snapshot, team + 0x30) != club_address:
                        raise ValueError('Staff club team backlink changed')
                    manager = players.u64(snapshot(team + 0x80, 8))
                    if manager:
                        addresses.add(manager)
                        manager_count += 1
                pending = []
                if len(addresses) > 1000:
                    raise ValueError('Club staff exceeds reference bound')
                for address in sorted(addresses):
                    _, fields = staff.layout(snapshot, base, address)
                    person = address + fields[2]
                    index = int.from_bytes(snapshot(person + 8, 4), 'little')
                    database.staff_membership(snapshot, base, info, index, address)
                    person_record, identity = staff.decode(snapshot, base, address, include_attributes=include_attributes)
                    person_record['contract'] = staff.contract_club(snapshot, base, person, club_address, include_job)
                    if include_contract_dates:
                        person_record['contract']['dates'] = contract_dates.decode(snapshot, base, person)
                    if include_contract_status:
                        person_record['contract']['status'] = contract_status.decode(snapshot, base, person)
                    if include_wage:
                        person_record['contract']['wage'] = wages.decode(snapshot, base, person, currency)
                    if include_contract_bonuses:
                        person_record['contract']['bonuses'] = contract_bonuses.decode(snapshot, base, person, currency)
                    if include_contract_terms:
                        person_record['contract']['terms'] = contract_terms.decode(snapshot, base, person, currency)
                    pending.append((address, index, person_record, identity))
                snapshot.verify()
            except (ValueError, IndexError) as exc:
                raise BridgeError(f'Club staff rejected; no partial roster returned: {exc}') from exc
            if len(self.staff_refs) + len(pending) > 1000:
                self.staff_refs.clear()
            result = []
            for address, index, person_record, identity in pending:
                ref = secrets.token_urlsafe(12)
                self.staff_refs[ref] = {'address': address, 'identity': identity, 'tables': tables,
                                        'world_bound': True, 'database_index': index}
                result.append({**person_record, 'staff_ref': ref})
            result.sort(key=lambda person: (person['display_name'].casefold(), person['birth_date']))
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': self._public_save(record), 'club': club, 'staff': result, 'count': len(result),
                    'native_vector_counts': vector_counts, 'team_manager_links': manager_count,
                    'evidence': 'three_club_vectors_and_team_managers_with_person_table_and_contract_backlinks',
                    'limitations': 'Deduplicates three native club staff vectors and club team managers. Every returned person has a checked contract to this club. Optional ratings expose underlying stored values; optional job titles follow the native contract/team conversion. Board/support staff and every UI staff category are not proven covered. Reads are non-atomic.'}

    def get_staff(self, session_id: str, staff_ref: str, include_club: bool = False,
                  include_attributes: bool = False, include_job: bool = False,
                  include_contract_dates: bool = False, include_wage: bool = False, include_contract_status: bool = False,
                  include_contract_bonuses: bool = False, include_contract_terms: bool = False) -> dict:
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            if type(include_contract_terms) is not bool:
                raise BridgeError('include_contract_terms must be a boolean.')
            if type(include_contract_bonuses) is not bool:
                raise BridgeError('include_contract_bonuses must be a boolean.')
            if type(include_attributes) is not bool:
                raise BridgeError('include_attributes must be a boolean.')
            if type(include_job) is not bool:
                raise BridgeError('include_job must be a boolean.')
            if type(include_club) is not bool:
                raise BridgeError('include_club must be a boolean.')
            if type(include_contract_dates) is not bool:
                raise BridgeError('include_contract_dates must be a boolean.')
            if type(include_contract_status) is not bool:
                raise BridgeError('include_contract_status must be a boolean.')
            if type(include_wage) is not bool:
                raise BridgeError('include_wage must be a boolean.')
            saved = self.staff_refs.get(staff_ref)
            if not saved:
                raise BridgeError('Unknown or expired staff reference. Find the staff member again.')
            try:
                tables = self._player_layout(process)
                if tables != saved['tables']:
                    raise ValueError('Loaded staff layout changed')
                base = tables[0] - players.RVA[0]
                snapshot, _, _ = self._world_state(process, tables)
                info = database.table(snapshot, base, 'people')
                database.staff_membership(snapshot, base, info, saved['database_index'], saved['address'])
                record, identity = staff.decode(snapshot, base, saved['address'], include_club, include_attributes, include_job, include_contract_dates, include_wage, include_contract_status, include_contract_bonuses, include_contract_terms)
                if identity != saved['identity']:
                    raise ValueError('Staff identity changed')
                snapshot.verify()
            except (ValueError, IndexError, BridgeError) as exc:
                self.staff_refs.pop(staff_ref, None)
                raise BridgeError(f'Staff read rejected: {exc}') from exc
            return {'session_id': session_id, 'staff_ref': staff_ref, 'staff': record,
                    'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save_identity': 'native_binding_rechecked',
                    'limitations': 'Optional ratings expose underlying stored values. Optional job titles follow the native contract/team conversion. Optional contract dates distinguish fixed expiry, computed dynamic expiry and unavailable basic-contract fields. Optional contract status uses the native current-contract enum; specialized league contract types remain unsupported. Optional wages are weekly main-contract amounts in GBP; contributions and UI formatting are excluded. Optional bonuses expose six stored cash terms with absent and unavailable states; the terms option adds verified clause fields and retains unmapped kinds. Reads are non-atomic.'}

    def _stored_virtual_player(self, session_id, player_ref, saved, process, include_clubs,
                               include_profile, include_health, profile_policy):
        unavailable = None
        try:
            tables = self._player_layout(process)
            if tables != saved['tables'] or saved.get('record_kind') != 'virtual':
                raise ValueError('Stored virtual reference layout or kind changed')
            snapshot, _, _ = self._world_state(process, tables)
            inspected = virtual_identity.inspect(snapshot, saved['address'], tables)
            if (inspected['identity'] != saved['identity']
                    or inspected['native_identity']['database_index'] != saved.get('database_index')
                    or saved.get('person_offset') != 0x20):
                raise ValueError('Stored virtual player identity or membership changed')
            try:
                record, identity = self._roster_player(snapshot, saved['address'], tables, include_clubs, {},
                                                      include_profile, include_health, profile_policy)
            except virtual.ProfileUnavailableError as exc:
                if profile_policy != 'required' or inspected['cache_index'] >= 0:
                    raise
                unavailable = str(exc)
            if unavailable is None and profile_policy == 'available' and identity != saved['identity']:
                raise ValueError('Stored virtual player identity changed during readback')
            snapshot.verify()
            self._current(session_id)
        except (ValueError, IndexError, BridgeError) as exc:
            self.player_refs.pop(player_ref, None)
            raise BridgeError(f'Stored virtual player read rejected: {exc}') from exc
        if unavailable is not None:
            raise BridgeError(f'Player profile unavailable: {unavailable}')
        return {'session_id':session_id, 'player_ref':player_ref,
                'observed_at':datetime.now(timezone.utc).isoformat(), 'player':record,
                'save_identity':'native_binding_rechecked',
                'snapshot':'best-effort, non-atomic read with stored identity and source rechecks',
                **({'profile_policy':'available'} if profile_policy == 'available' else {})}

    def get_player(self, session_id: str, player_ref: str, include_clubs: bool = False,
                   include_contract_dates: bool = False, include_wage: bool = False, include_contract_status: bool = False, include_profile: bool = False, include_health: bool = False,
                   include_contract_bonuses: bool = False, include_contract_terms: bool = False, include_loan_contract: bool = False, profile_policy: str = "required", *, include_transfer_prices: bool = False) -> dict:
        from . import financial_details
        if type(include_transfer_prices) is not bool:
            raise BridgeError('include_transfer_prices must be a boolean.')
        self._profile_policy(profile_policy)
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            if type(include_loan_contract) is not bool:
                raise BridgeError('include_loan_contract must be a boolean.')
            if type(include_contract_terms) is not bool:
                raise BridgeError('include_contract_terms must be a boolean.')
            if type(include_contract_bonuses) is not bool:
                raise BridgeError('include_contract_bonuses must be a boolean.')
            if type(include_health) is not bool:
                raise BridgeError('include_health must be a boolean.')
            if type(include_profile) is not bool:
                raise BridgeError('include_profile must be a boolean.')
            if type(include_clubs) is not bool:
                raise BridgeError("include_clubs must be a boolean.")
            if type(include_contract_dates) is not bool:
                raise BridgeError('include_contract_dates must be a boolean.')
            if type(include_contract_status) is not bool:
                raise BridgeError('include_contract_status must be a boolean.')
            if type(include_wage) is not bool:
                raise BridgeError('include_wage must be a boolean.')
            saved = self.player_refs.get(player_ref)
            if not saved:
                raise BridgeError("Unknown or expired player reference. Find the player again.")
            if saved.get('binding_kind') == virtual_identity.BINDING_KIND:
                if (include_contract_dates or include_wage or include_contract_status or include_contract_bonuses
                        or include_contract_terms or include_loan_contract):
                    raise BridgeError('Virtual-player contract dates, wages, status, bonuses, terms and loan contracts are unsupported')
                result = self._stored_virtual_player(session_id, player_ref, saved, process, include_clubs,
                                                   include_profile, include_health, profile_policy)
                if include_transfer_prices:
                    result['player']['transfer_prices'] = {'state': 'unsupported_player_layout', 'currency': None}
                return result
            if saved.get('binding_kind') is not None:
                self.player_refs.pop(player_ref, None)
                raise BridgeError('Unsupported player reference binding kind')
            try:
                tables = self._player_layout(process)
                world_snapshot = None
                if saved.get("world_bound") or profile_policy == 'available':
                    world_snapshot, _, _ = self._world_state(process, tables)
                if 'database_index' in saved:
                    try:
                        info = database.table(world_snapshot, tables[0] - players.RVA[0], 'people')
                        database.player_membership(world_snapshot, tables[0] - players.RVA[0], info,
                                                   saved['database_index'], saved['address'])
                    except (ValueError, IndexError) as exc:
                        raise BridgeError(f'Player database membership changed: {exc}') from exc
                if tables != saved["tables"]:
                    raise BridgeError("Loaded player layout changed. Find the player again.")
                if include_transfer_prices or include_clubs or include_profile or include_health or include_contract_dates or include_wage or include_contract_status or include_contract_bonuses or include_contract_terms or include_loan_contract or saved.get('record_kind') == 'virtual' or profile_policy == 'available':
                    snapshot = world_snapshot or world.ReadSet(lambda a, n: self._read_memory(process, a, n))
                    try:
                        policy = 'required' if saved.get('record_kind') == 'virtual' else profile_policy
                        record, identity = self._roster_player(snapshot, saved['address'], tables, include_clubs, {}, include_profile, include_health, policy)
                        if profile_policy == 'available' and policy == 'required':
                            self._available_player(snapshot, saved['address'], tables, record)
                        if include_contract_dates or include_wage or include_contract_status or include_contract_bonuses or include_contract_terms or include_loan_contract:
                            if saved.get('record_kind') == 'virtual':
                                raise ValueError('Virtual-player contract dates, wages, status, bonuses, terms and loan contracts are unsupported')
                            person = saved['address'] + players.person_offset(snapshot, saved['address'], tables)
                        if include_transfer_prices:
                            record['transfer_prices'] = financial_details.player_prices(
                                snapshot, tables[0]-players.RVA[0], saved['address'], record.get('record_kind', 'actual'), self.plugin_identity[0])
                        if include_contract_dates:
                            record['contract_dates'] = contract_dates.decode(snapshot, tables[0] - players.RVA[0], person)
                        if include_contract_status:
                            record['contract_status'] = contract_status.decode(snapshot, tables[0] - players.RVA[0], person)
                        if include_wage:
                            record['wage'] = wages.decode(snapshot, tables[0] - players.RVA[0], person)
                        if include_contract_bonuses:
                            record['contract_bonuses'] = contract_bonuses.decode(snapshot, tables[0] - players.RVA[0], person)
                        if include_contract_terms:
                            record['contract_terms'] = contract_terms.decode(snapshot, tables[0] - players.RVA[0], person)
                        if include_loan_contract:
                            record['loan_contract'] = loan_contracts.decode(snapshot, tables[0] - players.RVA[0], saved['address'], person - saved['address'])
                        snapshot.verify()
                    except (ValueError, IndexError) as exc:
                        raise BridgeError(f"Player club record rejected: {exc}") from exc
                else:
                    record, identity = self._decode_player(process, saved["address"], tables)
                if identity != saved["identity"]:
                    raise BridgeError("Player identity changed. Find the player again.")
                if world_snapshot is not None:
                    try:
                        world_snapshot.verify()
                    except ValueError as exc:
                        raise BridgeError(f"Loaded game changed during player read: {exc}") from exc
            except BridgeError:
                self.player_refs.pop(player_ref, None)
                raise
            self._current(session_id)
            return {"session_id": session_id, "player_ref": player_ref,
                    "observed_at": datetime.now(timezone.utc).isoformat(), "player": record,
                    "save_identity": "native_binding_rechecked" if world_snapshot is not None else "unverified",
                    "snapshot": "best-effort, non-atomic read with identity recheck",
                    **({'profile_policy':'available'} if profile_policy == 'available' else {})}

    def get_player_match_form(self, session_id: str, player_ref: str,
                              team_ref: str | None = None,
                              mode: str = 'confirmed_appearances', limit: int = 5) -> dict:
        from . import live_player_match_form
        if not isinstance(player_ref, str) or not player_ref:
            raise BridgeError('Select a nonempty player_ref.')
        if team_ref is not None and (not isinstance(team_ref, str) or not team_ref):
            raise BridgeError('team_ref must be a nonempty reference or null.')
        try:
            live_player_match_form.select([], mode, limit)
        except ValueError as exc:
            raise BridgeError(str(exc)) from exc
        with self.lock, self._read_scope(session_id):
            try:
                return live_player_match_form.collect(self, session_id, player_ref, team_ref, mode, limit)
            except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
                self.player_refs.pop(player_ref, None)
                raise BridgeError(f'Player match form rejected; no partial result returned: {exc}') from exc

    def get_current_player_statistics(self, session_id: str, player_ref: str) -> dict:
        if not isinstance(player_ref, str) or not player_ref:
            raise BridgeError('Select a nonempty player_ref.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.player_refs.get(player_ref)
            if not saved:
                raise BridgeError('Unknown or expired player reference. Find the player again.')
            try:
                tables = self._player_layout(process)
                if tables != saved['tables']:
                    raise ValueError('Loaded player layout changed')
                snapshot, save, _ = self._world_state(process, tables)
                base = tables[0] - players.RVA[0]
                record, identity = self._roster_player(snapshot, saved['address'], tables, False, {})
                if identity != saved['identity']:
                    raise ValueError('Player identity changed')
                if record.get('record_kind', 'actual') != 'actual':
                    raise ValueError('Current statistics for virtual and combined player/staff records are unsupported')
                person = saved['address'] + players.person_offset(snapshot, saved['address'], tables)
                index = int.from_bytes(snapshot(person + 8, 4), 'little')
                if 'database_index' in saved and saved['database_index'] != index:
                    raise ValueError('Player database index changed')
                info = database.table(snapshot, base, 'people')
                database.player_membership(snapshot, base, info, index, saved['address'])
                statistics = current_player_statistics.decode(snapshot, base, saved['address'], tables)
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, BridgeError) as exc:
                self.player_refs.pop(player_ref, None)
                raise BridgeError(f'Current player statistics read rejected: {exc}') from exc
            return {'session_id': session_id, 'player_ref': player_ref,
                    'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save_identity': 'native_binding_rechecked', 'save': self._public_save(save),
                    'snapshot': 'best-effort, non-atomic read with identity and consumed-byte rechecks',
                    'player': {'name': record['name'], 'birth_date': record['birth_date'], 'record_kind': 'actual'},
                    'statistics': statistics}

    def compare_team_league_performance(self, session_id: str, team_ref: str,
                                       minimum_minutes: int = 450, limit: int = 5,
                                       include_history: bool = True) -> dict:
        if not isinstance(team_ref, str) or not team_ref:
            raise BridgeError('Select a nonempty team_ref.')
        integer(minimum_minutes, 0, 32767, 'minimum_minutes')
        integer(limit, 1, 25, 'limit')
        if type(include_history) is not bool:
            raise BridgeError('include_history must be a boolean.')
        with self.lock:
            self._current(session_id)
            try:
                return performance_comparison.collect(
                    self, session_id, team_ref, minimum_minutes, limit, include_history)
            except (ValueError, IndexError) as exc:
                raise BridgeError(f'Team League comparison rejected; no partial ranking returned: {exc}') from exc

    def get_player_statistics_history(self, session_id: str, player_ref: str) -> dict:
        if not isinstance(player_ref, str) or not player_ref:
            raise BridgeError('Select a nonempty player_ref.')
        with self.lock, self._read_scope(session_id):
            process = self._current(session_id)
            saved = self.player_refs.get(player_ref)
            if not saved:
                raise BridgeError('Unknown or expired player reference. Find the player again.')
            try:
                tables = self._player_layout(process)
                if tables != saved['tables']:
                    raise ValueError('Loaded player layout changed')
                snapshot, save, _ = self._world_state(process, tables)
                base = tables[0] - players.RVA[0]
                record, identity = self._roster_player(snapshot, saved['address'], tables, False, {})
                if identity != saved['identity']:
                    raise ValueError('Player identity changed')
                if record.get('record_kind', 'actual') != 'actual':
                    raise ValueError('Archived statistics for virtual and combined player/staff records are unsupported')
                person = saved['address'] + players.person_offset(snapshot, saved['address'], tables)
                index = int.from_bytes(snapshot(person + 8, 4), 'little')
                if 'database_index' in saved and saved['database_index'] != index:
                    raise ValueError('Player database index changed')
                info = database.table(snapshot, base, 'people')
                database.player_membership(snapshot, base, info, index, saved['address'])
                pending = []
                with stats_archive.open_player_archive(
                        snapshot, base, saved['address'], tables, process.pid) as source:
                    if source['state'] == 'decoded':
                        archived_player_statistics.verify_native(snapshot, base)
                        archive_stat_references.verify_native(snapshot, base)
                    for entry in source['records']:
                        prefix = archive_stat_references.decode_prefix(entry['raw'])
                        row = archived_player_statistics.decode_record(entry['raw'], prefix)
                        linked = archive_stat_references.resolve(snapshot, base, prefix)
                        pending.append(({'native_offset': entry['native_offset'], **row,
                                         'team': linked['team'], 'competition': linked['competition']},
                                        linked['_bindings']))
                    if source['state'] == 'decoded' and source['native_entry_count'] != (
                            len(pending) + len(source['skipped_entries'])):
                        raise ValueError('Statistics archive entry accounting disagrees')
                snapshot.verify()
                self._current(session_id)
            except (ValueError, IndexError, OSError, subprocess.SubprocessError, BridgeError) as exc:
                self.player_refs.pop(player_ref, None)
                raise BridgeError(f'Player statistics history read rejected: {exc}') from exc

            # Publish only after archive context exit and every memory recheck succeed.
            if len(self.team_refs) + len(pending) > 10000:
                self.team_refs.clear()
            if len(self.competition_refs) + len(pending) > 10000:
                self.competition_refs.clear()
            team_links, competition_links = {}, {}
            rows = []
            for row, bindings in pending:
                team, competition = row['team'], row['competition']
                if team is not None:
                    binding = bindings['team']
                    key = binding['address']
                    if key not in team_links:
                        ref = secrets.token_urlsafe(12)
                        self.team_refs[ref] = {**binding, 'tables': tables, 'source': 'competition',
                                              'label': f"{team['kind']} type {team['native_type_code']}"}
                        team_links[key] = ref
                    row['team'] = {**team, 'team_ref': team_links[key]}
                if competition is not None:
                    binding = bindings['competition']
                    key = binding['address']
                    if key not in competition_links:
                        ref = secrets.token_urlsafe(12)
                        self.competition_refs[ref] = {**binding, 'tables': tables}
                        competition_links[key] = ref
                    row['competition'] = {**competition, 'competition_ref': competition_links[key]}
                rows.append(row)
            history = {key: source[key] for key in ('state', 'reason', 'native_entry_count',
                       'skipped_entries', 'record_width', 'version', 'encoding', 'source_coverage')}
            history.update(rows=rows, returned_row_count=len(rows), limitations=(
                archived_player_statistics.LIMITATIONS + ' Stored team and competition links are '
                'archive context; they do not establish that each category was played in that competition. '
                'Resident cache sources, current statistics and starting playing history are not merged.'))
            return {'session_id': session_id, 'player_ref': player_ref,
                    'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save_identity': 'native_binding_rechecked', 'save': self._public_save(save),
                    'snapshot': 'best-effort, non-atomic read with identity, file and consumed-byte rechecks',
                    'player': {'name': record['name'], 'birth_date': record['birth_date'], 'record_kind': 'actual'},
                    'history': history}

    def get_loan_contract(self, session_id: str, player_ref: str) -> dict:
        if not isinstance(player_ref, str) or not player_ref:
            raise BridgeError('Select a nonempty player_ref.')
        response = self.get_player(session_id, player_ref, include_loan_contract=True)
        player = response['player']
        return {'session_id': session_id, 'player_ref': player_ref,
                'observed_at': response['observed_at'], 'save_identity': response['save_identity'],
                'player': {key: player[key] for key in ('name', 'birth_date', 'record_kind') if key in player},
                'loan_contract': player['loan_contract']}

    def get_contract_terms(self, session_id: str, player_ref: str | None = None,
                           staff_ref: str | None = None) -> dict:
        if (player_ref is None) == (staff_ref is None):
            raise BridgeError('Select exactly one player_ref or staff_ref.')
        reference = player_ref if player_ref is not None else staff_ref
        if not isinstance(reference, str) or not reference:
            raise BridgeError('Select a nonempty player_ref or staff_ref.')
        if player_ref is not None:
            response = self.get_player(session_id, player_ref, include_contract_terms=True)
            person = response['player']
            terms = person['contract_terms']
        else:
            response = self.get_staff(session_id, staff_ref, include_contract_terms=True)
            person = response['staff']
            terms = person['contract']['terms']
        return {'session_id': session_id, 'player_ref': player_ref, 'staff_ref': staff_ref,
                'observed_at': response['observed_at'], 'save_identity': response['save_identity'],
                'person': {key: person[key] for key in ('name', 'birth_date', 'record_kind') if key in person},
                'contract_terms': terms}

    def detach(self) -> dict:
        with self.lock:
            self._clear()
            return {"detached": True}

