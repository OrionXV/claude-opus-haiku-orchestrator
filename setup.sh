#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
marker='<!-- claude-orchestrator:start -->'

cat <<'BANNER'
+---------------------------------------+
|                                       |
|        O R C H E S T R A T O R        |
|            for Claude Code            |
|                                       |
|    Orchestrate with Opus or Fable.    |
|          Execute with Haiku.          |
|                                       |
+---------------------------------------+
BANNER
printf '%s\n' 'Interactive project setup'

cancel_input() {
    printf '\nSetup cancelled: input ended before setup was complete.\n' >&2
    exit 1
}

# Reads one line into input_value. A last line without a trailing newline is accepted;
# end of input with nothing read fails.
read_input() {
    input_value=
    IFS= read -r input_value || [ -n "$input_value" ] || return 1
}

printf '%s' 'Target repository path: '
read_input || cancel_input
target_path=$input_value

# Expand a leading ~ or ~/ the way a shell would for an unquoted argument.
case "$target_path" in
    '~') target_path=$HOME ;;
    '~/'*) target_path=$HOME/${target_path#"~/"} ;;
esac

if [ -z "$target_path" ] || [ ! -d "$target_path" ]; then
    printf 'Error: target must be an existing directory: %s\n' "${target_path:-<empty>}" >&2
    exit 1
fi

target_dir=$(CDPATH= cd -- "$target_path" && pwd -P)

# True when two physical paths are equal or one lies inside the other.
paths_overlap() {
    overlap_a=${1%/}/
    overlap_b=${2%/}/
    case "$overlap_b" in "$overlap_a"*) return 0 ;; esac
    case "$overlap_a" in "$overlap_b"*) return 0 ;; esac
    return 1
}

if paths_overlap "$target_dir" "$script_dir"; then
    printf 'Error: target repository must be different from the setup source directory.\n' >&2
    exit 1
fi

# Lower-case and trim surrounding blanks so answers such as " Pro " are accepted.
normalize() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

confirm() {
    prompt=$1
    default_yes=$2
    if [ "$default_yes" = yes ]; then
        suffix='[Y/n]'
    else
        suffix='[y/N]'
    fi

    while :; do
        printf '%s %s ' "$prompt" "$suffix"
        read_input || cancel_input

        answer=$(normalize "$input_value")
        case "$answer" in
            y|yes) return 0 ;;
            n|no) return 1 ;;
            '')
                if [ "$default_yes" = yes ]; then
                    return 0
                fi
                return 1
                ;;
            *) printf '%s\n' 'Please answer yes or no.' ;;
        esac
    done
}

select_profile() {
    printf '%s\n' 'Choose Profile to install'
    printf '%s\n' '  1) max - Opus 5.5 root, Haiku 5.5 subagents, Opus reviewer (default)'
    printf '%s\n' '  2) pro - Sonnet 5.5 root, Haiku 5.5 subagents, Opus reviewer'
    printf '%s\n' '  3) max-2-subagents - Opus 5.5 root, Haiku 5.5 subagents (2 concurrent), Opus reviewer'
    printf '%s\n' '  4) pro-2-subagents - Sonnet 5.5 root, Haiku 5.5 subagents (2 concurrent), Opus reviewer'
    printf '%s\n' '  5) fable-xhigh-haiku-max - Fable 5.1 root (xhigh), Haiku 5.5 subagents, Fable 5.1 reviewer (max)'
    printf '%s\n' '  6) fable-medium-haiku-max - Fable 5.1 root and reviewer (medium), Haiku 5.5 subagents'

    while :; do
        printf '%s' 'Select Profile [1-6] (default 1): '
        read_input || cancel_input

        answer=$(normalize "$input_value")
        case "$answer" in
            ''|1|max) profile_name=max; return 0 ;;
            2|pro) profile_name=pro; return 0 ;;
            3|max-2-subagents) profile_name=max-2-subagents; return 0 ;;
            4|pro-2-subagents) profile_name=pro-2-subagents; return 0 ;;
            5|fable-xhigh-haiku-max) profile_name=fable-xhigh-haiku-max; return 0 ;;
            6|fable-medium-haiku-max) profile_name=fable-medium-haiku-max; return 0 ;;
            *) printf '%s\n' 'Please enter a listed profile number or name.' ;;
        esac
    done
}

# Refuse to write through symlinks or over non-directories on the way to a destination.
# Arguments: component name, then every parent directory that must be a real directory.
check_parent_dirs() {
    check_component=$1
    shift
    for parent_path in "$@"; do
        if [ -L "$parent_path" ]; then
            printf 'Skipped %s: the existing target contains a symbolic link (%s).\n' \
                "$check_component" "$parent_path" >&2
            return 1
        fi
        if [ -e "$parent_path" ] && [ ! -d "$parent_path" ]; then
            printf 'Skipped %s: source and target types are incompatible.\n' "$check_component" >&2
            return 1
        fi
    done
    return 0
}

create_parent_dirs() {
    for parent_path in "$@"; do
        if [ ! -d "$parent_path" ]; then
            mkdir "$parent_path"
        fi
    done
}

# Lists existing destination files whose content differs from the source (they would be replaced).
changed_paths() {
    changed_source=$1
    changed_destination=$2
    changed_name=$3
    find "$changed_source" -type f -print | while IFS= read -r source_file; do
        relative_path=${source_file#"$changed_source"/}
        destination_file=$changed_destination/$relative_path
        if [ -f "$destination_file" ] && ! cmp -s "$source_file" "$destination_file"; then
            printf '%s/%s\n' "$changed_name" "$relative_path"
        fi
    done
}

# Lists source files that the destination does not have yet.
new_paths() {
    new_source=$1
    new_destination=$2
    find "$new_source" -type f -print | while IFS= read -r source_file; do
        relative_path=${source_file#"$new_source"/}
        destination_file=$new_destination/$relative_path
        if [ ! -e "$destination_file" ] && [ ! -L "$destination_file" ]; then
            printf '%s\n' "$relative_path"
        fi
    done
}

# Lists source entries whose destination already exists with a different type.
merge_conflicts() {
    conflict_source=$1
    conflict_destination=$2
    find "$conflict_source" -print | while IFS= read -r source_entry; do
        if [ "$source_entry" = "$conflict_source" ]; then
            continue
        fi
        relative_path=${source_entry#"$conflict_source"/}
        destination_entry=$conflict_destination/$relative_path
        if [ -d "$source_entry" ]; then
            if { [ -e "$destination_entry" ] || [ -L "$destination_entry" ]; } && [ ! -d "$destination_entry" ]; then
                printf '%s\n' "$relative_path"
            fi
        elif [ -f "$source_entry" ]; then
            if { [ -e "$destination_entry" ] || [ -L "$destination_entry" ]; } && [ ! -f "$destination_entry" ]; then
                printf '%s\n' "$relative_path"
            fi
        fi
    done
}

# Prints the first symbolic link on the path to a destination file that copying the source would
# write. Links elsewhere in the destination are ignored and never followed.
write_path_link() {
    link_source=$1
    link_destination=$2
    find "$link_source" -type f -print | while IFS= read -r source_file; do
        remaining=${source_file#"$link_source"/}
        current=$link_destination
        while :; do
            segment=${remaining%%/*}
            current=$current/$segment
            if [ -L "$current" ]; then
                printf '%s\n' "$current"
                break
            fi
            case "$remaining" in
                */*) remaining=${remaining#*/} ;;
                *) break ;;
            esac
        done
    done | sed -n '1p'
}

# Prints the frontmatter name of an agent file, or nothing when it has none.
agent_name() {
    awk '
        { sub(/\r$/, "") }
        NR == 1 { if ($0 != "---") exit; infront = 1; next }
        infront && $0 == "---" { exit }
        infront && /^name:/ { print; exit }
    ' "$1" | sed 's/^name:[[:space:]]*//; s/[[:space:]]*$//' | tr -d "\"'"
}

# Lists existing agent files, other than the ones being installed, that declare a bundled role name.
agent_name_clashes() {
    clash_source=$1
    clash_destination=$2
    find "$clash_destination" -type f -name '*.md' -print | while IFS= read -r existing_file; do
        relative_path=${existing_file#"$clash_destination"/}
        if [ -f "$clash_source/$relative_path" ]; then
            continue
        fi
        clash_name=$(agent_name "$existing_file")
        case "$clash_name" in
            explorer|worker|tester|reviewer|researcher)
                printf '%s (name: %s)\n' "$relative_path" "$clash_name"
                ;;
        esac
    done
}

# Copies a directory component (.claude/agents or .claude/skills/claude-orchestrator).
# Arguments: component name, source directory, then the parent directories to check.
install_directory() {
    component=$1
    source_path=$2
    shift 2
    destination_path=$target_dir/$component
    component_installed=no

    if [ ! -e "$source_path" ]; then
        printf 'Error: setup source is missing: %s\n' "$source_path" >&2
        exit 1
    fi

    if ! check_parent_dirs "$component" "$@"; then
        return 0
    fi

    if [ -L "$destination_path" ]; then
        printf 'Skipped %s: the existing target is a symbolic link.\n' "$component" >&2
        return 0
    fi

    if [ ! -e "$destination_path" ]; then
        create_parent_dirs "$@"
        cp -R "$source_path" "$destination_path"
        component_installed=yes
        printf 'Installed %s.\n' "$component"
        return 0
    fi

    if [ ! -d "$destination_path" ]; then
        printf 'Skipped %s: source and target types are incompatible.\n' "$component" >&2
        return 0
    fi

    link_path=$(write_path_link "$source_path" "$destination_path")
    if [ -n "$link_path" ]; then
        printf 'Skipped %s: the existing target contains a symbolic link (%s).\n' \
            "$component" "$link_path" >&2
        return 0
    fi

    conflict_list=$(merge_conflicts "$source_path" "$destination_path")
    if [ -n "$conflict_list" ]; then
        printf 'Skipped %s: source and target types conflict at:\n' "$component" >&2
        printf '%s\n' "$conflict_list" | sed 's/^/  /' >&2
        return 0
    fi

    if [ "$component" = .claude/agents ]; then
        clash_list=$(agent_name_clashes "$source_path" "$destination_path")
        if [ -n "$clash_list" ]; then
            printf '%s\n' 'WARNING: these existing agents use the same name and may shadow the installed ones:'
            printf '%s\n' "$clash_list" | sed 's|^|  - .claude/agents/|'
        fi
    fi

    overwrite_list=$(changed_paths "$source_path" "$destination_path" "$component")
    added_list=$(new_paths "$source_path" "$destination_path")
    if [ -z "$overwrite_list" ] && [ -z "$added_list" ]; then
        printf '%s already up to date.\n' "$component"
        return 0
    fi

    if [ -n "$overwrite_list" ]; then
        printf '%s\n' 'WARNING: the following existing files will be overwritten:'
        printf '%s\n' "$overwrite_list" | sed 's/^/  - /'
        if ! confirm "Update $component? New files will be added; only paths listed above will be replaced." no; then
            printf 'Skipped %s (existing target left unchanged).\n' "$component"
            return 0
        fi
    fi

    cp -R "$source_path"/. "$destination_path"/
    component_installed=yes
    printf 'Updated %s.\n' "$component"
}

# Merges the profile settings into an existing settings file with python3.
# Mode "plan" prints the keys that would change (exit 0), reports nothing to do (exit 4),
# or skips with a message (exit 3). Mode "write" saves the merged file, or exits 5 when the
# file cannot be written.
merge_settings() {
    python3 - "$1" "$2" "$3" <<'PY'
import json
import os
import shutil
import sys
import tempfile

source_path, destination_path, mode = sys.argv[1], sys.argv[2], sys.argv[3]
label = ".claude/settings.json"
MISSING = object()
SKIP, NOTHING, WRITE_FAILED = 3, 4, 5


def show(value):
    return "<unset>" if value is MISSING else json.dumps(value, ensure_ascii=False)


with open(source_path, encoding="utf-8") as handle:
    profile = json.load(handle)

try:
    with open(destination_path, encoding="utf-8-sig") as handle:
        existing = json.load(handle)
except OSError:
    print(f"Skipped {label}: existing file could not be read; left unchanged.")
    sys.exit(SKIP)
except ValueError:
    print(f"Skipped {label}: existing file is not valid JSON; left unchanged.")
    sys.exit(SKIP)

if not isinstance(existing, dict):
    print(f"Skipped {label}: top-level value is not a JSON object; left unchanged.")
    sys.exit(SKIP)
if "env" in existing and not isinstance(existing["env"], dict):
    print(f"Skipped {label}: 'env' is not a JSON object; left unchanged.")
    sys.exit(SKIP)

existing_env = existing.get("env", {})
changes = []
top_updates = {}
env_updates = {}

if "$schema" not in existing:
    changes.append(("$schema", MISSING, profile["$schema"]))
for key in ("model", "effortLevel"):
    old = existing.get(key, MISSING)
    if old != profile[key]:
        changes.append((key, old, profile[key]))
        top_updates[key] = profile[key]
for key, new in profile["env"].items():
    old = existing_env.get(key, MISSING)
    if old != new:
        changes.append((f"env.{key}", old, new))
        env_updates[key] = new

if not changes:
    print(f"{label} already matches the profile; nothing to merge.")
    sys.exit(NOTHING)

if mode == "plan":
    print(f"Keys that will change in {label}:")
    for key, old, new in changes:
        print(f"  {key}: {show(old)} -> {show(new)}")
    sys.exit(0)

merged = {}
if "$schema" not in existing:
    merged["$schema"] = profile["$schema"]
merged.update(existing)
merged.update(top_updates)
env = dict(existing_env)
env.update(env_updates)
merged["env"] = env

directory = os.path.dirname(destination_path)
temp_path = None
try:
    fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".settings-", suffix=".json.tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    shutil.copymode(destination_path, temp_path)
    os.replace(temp_path, destination_path)
    temp_path = None
except OSError:
    if temp_path is not None and os.path.exists(temp_path):
        os.unlink(temp_path)
    sys.exit(WRITE_FAILED)
except BaseException:
    if temp_path is not None and os.path.exists(temp_path):
        os.unlink(temp_path)
    raise
PY
}

install_settings() {
    settings_source=$1
    settings_destination=$target_dir/.claude/settings.json
    component_installed=no

    if [ ! -e "$settings_source" ]; then
        printf 'Error: setup source is missing: %s\n' "$settings_source" >&2
        exit 1
    fi

    if ! check_parent_dirs .claude/settings.json "$target_dir/.claude"; then
        return 0
    fi

    if [ -L "$settings_destination" ]; then
        printf '%s\n' 'Skipped .claude/settings.json: the existing target is a symbolic link.' >&2
        return 0
    fi

    if [ ! -e "$settings_destination" ]; then
        create_parent_dirs "$target_dir/.claude"
        cp "$settings_source" "$settings_destination"
        component_installed=yes
        printf '%s\n' 'Installed .claude/settings.json.'
        return 0
    fi

    if [ ! -f "$settings_destination" ]; then
        printf '%s\n' 'Skipped .claude/settings.json: source and target types are incompatible.' >&2
        return 0
    fi

    # `command -v` alone is not enough: the macOS python3 stub exists without developer tools.
    if ! python3 -c 'import json' >/dev/null 2>&1; then
        printf '%s\n' 'Skipped .claude/settings.json: python3 is required to merge into an existing file.'
        return 0
    fi

    plan_status=0
    merge_settings "$settings_source" "$settings_destination" plan || plan_status=$?
    case "$plan_status" in
        0) ;;
        3) return 0 ;;
        4) return 0 ;;
        *)
            printf '%s\n' 'Skipped .claude/settings.json: could not read the existing file.'
            return 0
            ;;
    esac

    if ! confirm 'Merge into existing .claude/settings.json?' no; then
        printf '%s\n' 'Skipped .claude/settings.json (existing target left unchanged).'
        return 0
    fi

    write_status=0
    merge_settings "$settings_source" "$settings_destination" write || write_status=$?
    if [ "$write_status" -ne 0 ]; then
        printf '%s\n' 'Skipped .claude/settings.json: could not write the file.'
        return 0
    fi
    component_installed=yes
    printf '%s\n' 'Merged .claude/settings.json.'
}

# Claude Code stops reading AGENTS.md files above a directory once a CLAUDE.md is present.
warn_ancestor_agents() {
    ancestor_dir=$target_dir
    while [ "$ancestor_dir" != / ]; do
        ancestor_dir=$(dirname -- "$ancestor_dir")
        if [ -e "${ancestor_dir%/}/AGENTS.md" ] || [ -L "${ancestor_dir%/}/AGENTS.md" ]; then
            printf 'Note: %s/AGENTS.md exists above the target; Claude Code stops reading AGENTS.md files once a CLAUDE.md is present. Add an @-import if you still need it.\n' \
                "${ancestor_dir%/}"
        fi
    done
}

install_claude_md() {
    instructions_source=$1
    instructions_destination=$target_dir/CLAUDE.md
    component_installed=no

    if [ ! -e "$instructions_source" ]; then
        printf 'Error: setup source is missing: %s\n' "$instructions_source" >&2
        exit 1
    fi

    if [ -L "$instructions_destination" ]; then
        link_target=$(readlink "$instructions_destination")
        printf 'Skipped CLAUDE.md: it is a symbolic link to %s. Append the contents of %s to that file manually.\n' \
            "$link_target" "$instructions_source" >&2
        return 0
    fi

    if [ ! -e "$instructions_destination" ]; then
        has_root_agents=no
        if [ -e "$target_dir/AGENTS.md" ] || [ -L "$target_dir/AGENTS.md" ]; then
            has_root_agents=yes
        fi
        has_claude_agents=no
        if [ -e "$target_dir/.claude/AGENTS.md" ] || [ -L "$target_dir/.claude/AGENTS.md" ]; then
            has_claude_agents=yes
        fi
        {
            # Claude Code reads AGENTS.md only when CLAUDE.md is absent, so import it explicitly.
            if [ "$has_root_agents" = yes ]; then
                printf '@AGENTS.md\n'
            fi
            if [ "$has_claude_agents" = yes ]; then
                printf '@.claude/AGENTS.md\n'
            fi
            if [ "$has_root_agents" = yes ] || [ "$has_claude_agents" = yes ]; then
                printf '\n'
            fi
            cat "$instructions_source"
        } > "$instructions_destination"
        component_installed=yes
        printf '%s\n' 'Installed CLAUDE.md.'
        warn_ancestor_agents
        return 0
    fi

    if [ ! -f "$instructions_destination" ]; then
        printf '%s\n' 'Skipped CLAUDE.md: source and target types are incompatible.' >&2
        return 0
    fi

    if grep -F -q -- "$marker" "$instructions_destination"; then
        printf '%s\n' 'Skipped CLAUDE.md: instructions already present.'
        return 0
    fi

    printf '\n\n' >> "$instructions_destination"
    cat "$instructions_source" >> "$instructions_destination"
    component_installed=yes
    printf '%s\n' 'Appended instructions to CLAUDE.md. Existing contents preserved.'
}

select_profile

profile_dir=$script_dir/profiles/$profile_name/claude
installed=0
for component in .claude/agents .claude/skills/claude-orchestrator .claude/settings.json CLAUDE.md; do
    if confirm "Install $component?" yes; then
        component_installed=no
        case "$component" in
            .claude/agents)
                install_directory .claude/agents "$profile_dir/agents" "$target_dir/.claude"
                ;;
            .claude/skills/claude-orchestrator)
                install_directory .claude/skills/claude-orchestrator \
                    "$profile_dir/skills/claude-orchestrator" \
                    "$target_dir/.claude" "$target_dir/.claude/skills"
                ;;
            .claude/settings.json)
                install_settings "$profile_dir/settings.json"
                ;;
            CLAUDE.md)
                install_claude_md "$script_dir/CLAUDE.md"
                ;;
        esac
        if [ "$component_installed" = yes ]; then
            installed=$((installed + 1))
        fi
    else
        printf 'Skipped %s.\n' "$component"
    fi
done

printf '\nSetup complete. %s component(s) installed in %s (profile: %s).\n' "$installed" "$target_dir" "$profile_name"
printf '%s\n' 'See guides/ for model, effort and fast-mode options.'
