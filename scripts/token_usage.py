#!/usr/bin/env python3
"""Report token usage for a Claude Code session and its subagents.

Claude Code writes one transcript per session to
~/.claude/projects/<slug>/<session-id>.jsonl (under $CLAUDE_CONFIG_DIR/projects
when that variable is set), where <slug> is the working directory with every
non-alphanumeric character replaced by "-". Slugs longer than 200 characters
are cut to 200 and suffixed with "-<hash>". Subagents live beside it:

  <slug>/<session-id>/subagents/agent-<id>.jsonl        (+ agent-<id>.meta.json)
  <slug>/<session-id>/subagents/workflows/wf_*/agent-<id>.jsonl
  <slug>/agent-<id>.jsonl, workflow-agent-<id>.jsonl    (remote sessions, flat)

The meta.json "agentType" names the subagent role. The root and subagent
transcripts record "message.model" and the effort level ("effort") on every
assistant line.

Counting rules:
  * One API response is written as several assistant lines sharing
    message.id, each repeating the usage. Each id is counted once, using the
    last line's usage.
  * A resumed session copies earlier lines into its new transcript. A
    message.id belongs to the transcript that started first, judged within the
    session's project directory.
  * Root transcripts also mirror the lines of workflow subagents as sidechain
    lines. They are skipped when the matching subagent file exists; when it
    does not, they are reported as a subagent counted once.
  * "<synthetic>" entries (no API call) and malformed lines are skipped.

Usage:
  scripts/token_usage.py --list [--limit N] [--date YYYY-MM-DD] [--project PATH]
  scripts/token_usage.py --session <id-or-prefix> [--format md|json] [--projects-dir DIR]
  scripts/token_usage.py --latest [--format md|json] [--date YYYY-MM-DD] [--project PATH]

--project PATH keeps sessions whose project directory is PATH's slug, or whose
recorded working directory is PATH (this covers remote "ssh-*" directories).

Exit codes: 0 ok, 1 nothing found, 2 bad arguments or ambiguous session prefix.
Standard library only. Read-only: it never modifies transcript files.
"""

from __future__ import annotations

import argparse
import json
import os
import string
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SYNTHETIC_MODEL = "<synthetic>"
UTC_MIN = datetime.min.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


@dataclass
class Msg:
    mid: str
    model: str
    effort: str | None
    input: int
    cache_write: int
    cache_read: int
    output: int
    sidechain: bool
    agent_id: str | None
    attribution: str | None
    ts: str | None


@dataclass
class FileInfo:
    path: Path
    first_ts: str | None = None
    last_ts: str | None = None
    cwd: str | None = None
    version: str | None = None
    msgs: list[Msg] = field(default_factory=list)


_FILE_CACHE: dict[Path, FileInfo] = {}


def parse_ts(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _str(value) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_file(path: Path) -> FileInfo:
    """Parse one transcript into assistant messages that carry usage. Cached."""
    cached = _FILE_CACHE.get(path)
    if cached is not None:
        return cached
    info = FileInfo(path=path)
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return info
    with handle:
        for lineno, line in enumerate(handle):
            obj = _load_line(line)
            if obj is None:
                continue
            ts = _str(obj.get("timestamp"))
            if ts:
                if info.first_ts is None:
                    info.first_ts = ts
                if info.last_ts is None or ts > info.last_ts:
                    info.last_ts = ts
            if info.cwd is None:
                info.cwd = _str(obj.get("cwd"))
            if info.version is None:
                info.version = _str(obj.get("version"))
            if obj.get("type") != "assistant":
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            model = msg.get("model")
            usage = msg.get("usage")
            if not isinstance(model, str) or model == SYNTHETIC_MODEL or not isinstance(usage, dict):
                continue
            mid = _str(msg.get("id")) or _str(obj.get("uuid")) or f"line-{lineno}"
            info.msgs.append(
                Msg(
                    mid=mid,
                    model=model,
                    effort=_str(obj.get("effort")),
                    input=_int(usage.get("input_tokens")),
                    cache_write=_int(usage.get("cache_creation_input_tokens")),
                    cache_read=_int(usage.get("cache_read_input_tokens")),
                    output=_int(usage.get("output_tokens")),
                    sidechain=obj.get("isSidechain") is True,
                    agent_id=_str(obj.get("agentId")),
                    attribution=_str(obj.get("attributionAgent")),
                    ts=ts,
                )
            )
    _FILE_CACHE[path] = info
    return info


def peek_session(path: Path, max_lines: int = 500) -> tuple[str | None, str | None]:
    """Cheap read of the first timestamp and cwd, for listing sessions."""
    first_ts = cwd = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for count, line in enumerate(fh):
                if count >= max_lines:
                    break
                obj = _load_line(line)
                if obj is None:
                    continue
                if first_ts is None:
                    first_ts = _str(obj.get("timestamp"))
                if cwd is None:
                    cwd = _str(obj.get("cwd"))
                if first_ts and cwd:
                    break
    except OSError:
        pass
    return first_ts, cwd


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

MAX_SLUG_LENGTH = 200
_ASCII_ALNUM = frozenset(string.ascii_letters + string.digits)
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def default_projects_dir() -> Path:
    """$CLAUDE_CONFIG_DIR/projects when that variable is set, else ~/.claude/projects."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir).expanduser() if config_dir else Path("~/.claude").expanduser()
    return base / "projects"


def _utf16_units(text: str) -> list[int]:
    data = text.encode("utf-16-le", "surrogatepass")
    return [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]


def _sanitize_hash(text: str) -> int:
    """Claude Code's string hash: h = 31*h + unit over UTF-16 units, as int32."""
    h = 0
    for unit in _utf16_units(text):
        h = (31 * h + unit) & 0xFFFFFFFF
    return h - 2**32 if h >= 2**31 else h


def _base36(n: int) -> str:
    digits = []
    while True:
        n, r = divmod(n, 36)
        digits.append(_BASE36[r])
        if n == 0:
            break
    return "".join(reversed(digits))


def slug_for(path: Path) -> str:
    """The project directory name Claude Code derives from a working directory."""
    text = str(path)
    sanitized = "".join(
        ch if ch in _ASCII_ALNUM else "-" * (2 if ord(ch) > 0xFFFF else 1) for ch in text
    )
    if len(sanitized) <= MAX_SLUG_LENGTH:
        return sanitized
    return f"{sanitized[:MAX_SLUG_LENGTH]}-{_base36(abs(_sanitize_hash(text)))}"


def slugify(path_text: str) -> str:
    return slug_for(Path(path_text).expanduser().resolve())


@dataclass
class DirIndex:
    """Transcript files of one project directory, listed once."""

    roots: list[Path]
    flat_agents: list[Path]


def list_project_dir(directory: Path) -> DirIndex:
    roots: list[Path] = []
    flat: list[Path] = []
    for path in sorted(directory.glob("*.jsonl")):
        (flat if is_agent_name(path.name) else roots).append(path)
    return DirIndex(roots=roots, flat_agents=flat)


@dataclass
class Session:
    root: Path
    sid: str
    started: datetime | None
    cwd: str | None
    index: DirIndex = field(repr=False)
    _agents: list[Path] | None = field(default=None, repr=False)

    @property
    def slug(self) -> str:
        return self.root.parent.name

    @property
    def agents(self) -> list[Path]:
        # Resolved on first use: listing sessions does not need subagent files.
        if self._agents is None:
            self._agents = agent_files(self.root, self.index)
        return self._agents


def is_agent_name(name: str) -> bool:
    return name.startswith("agent-") or name.startswith("workflow-agent-")


def agent_id_from_name(name: str) -> str:
    stem = name[: -len(".jsonl")] if name.endswith(".jsonl") else name
    for prefix in ("workflow-agent-", "agent-"):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def agent_files(root: Path, index: DirIndex) -> list[Path]:
    found: list[Path] = []
    session_dir = root.parent / root.name[: -len(".jsonl")]
    if session_dir.is_dir():
        found += [p for p in session_dir.rglob("*.jsonl") if is_agent_name(p.name)]
    # Remote sessions keep their agents flat beside the root transcript. That
    # only applies when the directory holds exactly one session.
    if len(index.roots) == 1:
        found += index.flat_agents
    return sorted(set(found))


def same_directory(cwd: str | None, target: Path) -> bool:
    if not cwd:
        return False
    try:
        return Path(cwd).resolve() == target
    except (OSError, RuntimeError, ValueError):
        return False


def discover_sessions(projects_dir: Path, project: Path | None = None) -> list[Session]:
    """Every root transcript, newest first.

    With `project` (a resolved path), keep sessions whose project directory is
    that path's slug or whose recorded cwd is that path. Directories whose name
    is not the slug are read only up to their first cwd line.
    """
    target_slug = slug_for(project) if project is not None else None
    sessions: list[Session] = []
    for directory in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        index = list_project_dir(directory)
        slug_match = target_slug is not None and directory.name == target_slug
        for root in index.roots:
            first_ts, cwd = peek_session(root)
            if project is not None and not slug_match and not same_directory(cwd, project):
                continue
            sessions.append(
                Session(
                    root=root,
                    sid=root.name[: -len(".jsonl")],
                    started=parse_ts(first_ts),
                    cwd=cwd,
                    index=index,
                )
            )
    sessions.sort(key=lambda s: s.started or UTC_MIN, reverse=True)
    return sessions


def local_date(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d")


def filter_by_date(sessions: list[Session], date: str | None) -> list[Session]:
    if date is None:
        return sessions
    return [s for s in sessions if s.started is not None and local_date(s.started) == date]


def owner_index(roots: list[Path]) -> dict[str, str]:
    """Map each message.id to the root transcript that started first."""
    best: dict[str, tuple[str, str]] = {}
    for root in roots:
        info = parse_file(root)
        key = (info.first_ts or "", str(root))
        for m in info.msgs:
            current = best.get(m.mid)
            if current is None or key < current:
                best[m.mid] = key
    return {mid: path for mid, (_, path) in best.items()}


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def agent_role(path: Path, info: FileInfo) -> str:
    meta_path = path.parent / (path.name[: -len(".jsonl")] + ".meta.json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = None
    if isinstance(meta, dict) and _str(meta.get("agentType")):
        return meta["agentType"]
    attributions = Counter(m.attribution for m in info.msgs if m.attribution)
    if attributions:
        return attributions.most_common(1)[0][0]
    return "subagent"


def dedupe(msgs: list[Msg]) -> list[Msg]:
    last: dict[str, Msg] = {}
    for m in msgs:
        last[m.mid] = m
    return list(last.values())


@dataclass
class ModelStats:
    responses: int = 0
    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0
    efforts: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return self.input + self.cache_write + self.cache_read + self.output

    def top_effort(self) -> str | None:
        return self.efforts.most_common(1)[0][0] if self.efforts else None

    def add(self, other: ModelStats) -> None:
        self.responses += other.responses
        self.input += other.input
        self.cache_write += other.cache_write
        self.cache_read += other.cache_read
        self.output += other.output
        self.efforts.update(other.efforts)


def summarize(msgs: list[Msg]) -> dict[str, ModelStats]:
    out: dict[str, ModelStats] = {}
    for m in msgs:
        s = out.setdefault(m.model, ModelStats())
        s.responses += 1
        s.input += m.input
        s.cache_write += m.cache_write
        s.cache_read += m.cache_read
        s.output += m.output
        if m.effort:
            s.efforts[m.effort] += 1
    return out


@dataclass
class Thread:
    key: str
    role: str
    started: datetime | None
    ended: datetime | None
    stats: dict[str, ModelStats]

    @property
    def duration(self) -> int | None:
        if self.started and self.ended and self.ended >= self.started:
            return int((self.ended - self.started).total_seconds())
        return None


@dataclass
class Report:
    session: Session
    threads: list[Thread]
    cwd: str | None
    version: str | None


def build_report(session: Session, owners: dict[str, str]) -> Report:
    mine = str(session.root)
    root = parse_file(session.root)
    matched = {agent_id_from_name(p.name) for p in session.agents}
    owned = [m for m in root.msgs if owners.get(m.mid, mine) == mine]

    threads = [
        Thread(
            key=session.sid,
            role="root",
            started=parse_ts(root.first_ts),
            ended=parse_ts(root.last_ts),
            stats=summarize(dedupe([m for m in owned if not m.sidechain])),
        )
    ]
    for path in session.agents:
        info = parse_file(path)
        stats = summarize(dedupe(info.msgs))
        if not stats:
            continue
        threads.append(
            Thread(
                key=agent_id_from_name(path.name),
                role=agent_role(path, info),
                started=parse_ts(info.first_ts),
                ended=parse_ts(info.last_ts),
                stats=stats,
            )
        )

    # Workflow subagents mirrored into the root transcript without their own file.
    unmatched: dict[str, list[Msg]] = defaultdict(list)
    for m in owned:
        if m.sidechain and m.agent_id and m.agent_id not in matched:
            unmatched[m.agent_id].append(m)
    for agent_id, msgs in sorted(unmatched.items()):
        stamps = sorted(m.ts for m in msgs if m.ts)
        roles = Counter(m.attribution for m in msgs if m.attribution).most_common(1)
        threads.append(
            Thread(
                key=agent_id,
                role=roles[0][0] if roles else "subagent",
                started=parse_ts(stamps[0]) if stamps else None,
                ended=parse_ts(stamps[-1]) if stamps else None,
                stats=summarize(dedupe(msgs)),
            )
        )

    root_thread, others = threads[0], threads[1:]
    others.sort(key=lambda t: (t.started or UTC_MIN, t.key))
    return Report(
        session=session,
        threads=[root_thread, *others],
        cwd=root.cwd or session.cwd,
        version=root.version,
    )


def wall_seconds(threads: list[Thread]) -> int | None:
    starts = [t.started for t in threads if t.started]
    ends = [t.ended for t in threads if t.ended]
    if not starts or not ends:
        return None
    return int((max(ends) - min(starts)).total_seconds())


def cache_hit_rate(stats: ModelStats) -> float | None:
    denom = stats.input + stats.cache_write + stats.cache_read
    if denom == 0:
        return None
    return 100.0 * stats.cache_read / denom


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def render_markdown(report: Report) -> str:
    threads = report.threads
    rows_threads = [t for t in threads if t.stats]
    totals = ModelStats()
    per_model: dict[str, ModelStats] = defaultdict(ModelStats)
    per_model_threads: Counter = Counter()

    lines = [f"### Session `{report.session.sid[:8]}`", ""]
    lines.append(f"- cwd: `{report.cwd or '-'}`")
    lines.append(f"- claude code: `{report.version or '-'}`")
    lines.append(f"- threads: {len(threads)} (1 root, {len(threads) - 1} subagents)")
    lines.append(f"- wall time: {fmt_duration(wall_seconds(threads))}")
    lines.append("")
    lines.append("| Thread | Role | Model / effort | Responses | Input | Cache write | Cache read | Output | Total | Duration |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for t in rows_threads:
        for model, s in sorted(t.stats.items()):
            effort = s.top_effort() or "-"
            lines.append(
                f"| `{t.key[:8]}` | {t.role} | {model} / {effort} | {s.responses} | "
                f"{fmt_int(s.input)} | {fmt_int(s.cache_write)} | {fmt_int(s.cache_read)} | "
                f"{fmt_int(s.output)} | {fmt_int(s.total)} | {fmt_duration(t.duration)} |"
            )
            per_model[model].add(s)
            per_model_threads[model] += 1
            totals.add(s)
    lines.append("")
    lines.append("| Model | Threads | Responses | Input | Cache write | Cache read | Output | Total |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for model in sorted(per_model):
        s = per_model[model]
        lines.append(
            f"| {model} | {per_model_threads[model]} | {s.responses} | {fmt_int(s.input)} | "
            f"{fmt_int(s.cache_write)} | {fmt_int(s.cache_read)} | {fmt_int(s.output)} | {fmt_int(s.total)} |"
        )
    lines.append(
        f"| **all** | {len(rows_threads)} | {totals.responses} | {fmt_int(totals.input)} | "
        f"{fmt_int(totals.cache_write)} | {fmt_int(totals.cache_read)} | {fmt_int(totals.output)} | "
        f"{fmt_int(totals.total)} |"
    )
    rate = cache_hit_rate(totals)
    lines.append("")
    lines.append(f"Cache hit rate on input: {'n/a' if rate is None else f'{rate:.1f}%'}")
    lines.append("")
    lines.append(
        "Total = input + cache write + cache read + output. Cache hit rate = "
        "cache read / (input + cache write + cache read)."
    )
    return "\n".join(lines)


def _stats_dict(s: ModelStats) -> dict:
    return {
        "responses": s.responses,
        "input_tokens": s.input,
        "cache_creation_input_tokens": s.cache_write,
        "cache_read_input_tokens": s.cache_read,
        "output_tokens": s.output,
        "total_tokens": s.total,
    }


def render_json(report: Report) -> str:
    threads = report.threads
    totals = ModelStats()
    per_model: dict[str, ModelStats] = defaultdict(ModelStats)
    per_model_threads: Counter = Counter()
    thread_out = []
    for t in threads:
        models = {}
        for model, s in sorted(t.stats.items()):
            entry = _stats_dict(s)
            entry["effort"] = s.top_effort()
            models[model] = entry
            per_model[model].add(s)
            per_model_threads[model] += 1
            totals.add(s)
        thread_out.append(
            {
                "id": t.key,
                "role": t.role,
                "started": t.started.isoformat() if t.started else None,
                "ended": t.ended.isoformat() if t.ended else None,
                "duration_seconds": t.duration,
                "per_model": models,
            }
        )
    rate = cache_hit_rate(totals)
    payload = {
        "session": report.session.sid,
        "cwd": report.cwd,
        "claude_version": report.version,
        "wall_seconds": wall_seconds(threads),
        "threads": thread_out,
        "per_model": {
            model: {"threads": per_model_threads[model], **_stats_dict(s)}
            for model, s in sorted(per_model.items())
        },
        "totals": {"threads": sum(1 for t in threads if t.stats), **_stats_dict(totals)},
        "cache_hit_rate_on_input": None if rate is None else round(rate, 1),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def print_list(sessions: list[Session], limit: int) -> None:
    print("started (local)   session   subagents  cwd")
    for s in sessions[:limit]:
        started = s.started.astimezone().strftime("%Y-%m-%d %H:%M") if s.started else "-"
        print(f"{started:<17} {s.sid[:8]}  {len(s.agents):>9}  {s.cwd or '-'}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--list", action="store_true", help="List sessions, newest first.")
    modes.add_argument("--session", metavar="ID", help="Report one session by id or unique prefix.")
    modes.add_argument("--latest", action="store_true", help="Report the newest session that has subagents.")
    parser.add_argument("--limit", type=int, default=20, help="Rows to show with --list (default 20).")
    parser.add_argument("--date", help="Only sessions that started on this local date (YYYY-MM-DD).")
    parser.add_argument(
        "--project",
        metavar="PATH",
        help="Only sessions for working directory PATH: its project directory, or a recorded cwd of PATH.",
    )
    parser.add_argument(
        "--projects-dir",
        default=None,
        help="Claude Code projects directory (default $CLAUDE_CONFIG_DIR/projects if set, else ~/.claude/projects).",
    )
    parser.add_argument("--format", choices=("md", "json"), default="md")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not (args.list or args.session or args.latest):
        parser.print_help(sys.stderr)
        return 2
    if args.limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        return 2
    if args.date is not None:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(f"invalid --date {args.date!r}: expected YYYY-MM-DD", file=sys.stderr)
            return 2

    projects_dir = Path(args.projects_dir).expanduser() if args.projects_dir else default_projects_dir()
    if not projects_dir.is_dir():
        print(f"projects dir not found: {projects_dir}", file=sys.stderr)
        return 2

    project = Path(args.project).expanduser().resolve() if args.project else None
    selected = filter_by_date(discover_sessions(projects_dir, project), args.date)
    if not selected:
        print("no sessions found", file=sys.stderr)
        return 1

    if args.list:
        print_list(selected, args.limit)
        return 0

    if args.latest:
        chosen = next((s for s in selected if s.agents), None)
        if chosen is None:
            print("no session with subagents found", file=sys.stderr)
            return 1
    else:
        prefix = args.session.lower()
        matches = [s for s in selected if s.sid.lower().startswith(prefix)]
        if not matches:
            print(f"no session matches {args.session!r}", file=sys.stderr)
            return 1
        if len(matches) > 1:
            print(
                f"{args.session!r} matches {len(matches)} sessions; give a longer prefix",
                file=sys.stderr,
            )
            return 2
        chosen = matches[0]

    # Ownership is decided across the chosen session's project directory, so
    # copies in resumed sessions are not counted twice. A resume stays in the
    # project directory it started in, so no other directory is read.
    report = build_report(chosen, owner_index(chosen.index.roots))
    print(render_json(report) if args.format == "json" else render_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
