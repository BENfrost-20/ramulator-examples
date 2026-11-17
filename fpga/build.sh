#!/usr/bin/env bash
# Build artifacts only. This script never loads an xclbin onto a device.
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export FPGA_REPO_ROOT="$root"
config="${FPGA_BUILD_ENV:-$root/fpga/build.env.sh}"
args=()
light=0
help=0
cli_tmux_mode=''
cli_session=''
while (($#)); do
  case "$1" in
    --env)
      [[ $# -ge 2 ]] || { echo 'ERROR: --env requires a file' >&2; exit 2; }
      config="$2"; shift 2 ;;
    --env=*) config="${1#*=}"; shift ;;
    --tmux) cli_tmux_mode=auto; shift ;;
    --detach) cli_tmux_mode=detached; shift ;;
    --no-tmux) cli_tmux_mode=off; shift ;;
    --session)
      [[ $# -ge 2 ]] || { echo 'ERROR: --session requires a name' >&2; exit 2; }
      [[ -n "$2" ]] || { echo 'ERROR: --session requires a nonempty name' >&2; exit 2; }
      cli_session="$2"; shift 2 ;;
    --session=*)
      cli_session="${1#*=}"
      [[ -n "$cli_session" ]] || { echo 'ERROR: --session requires a nonempty name' >&2; exit 2; }
      shift ;;
    --help|-h) light=1; help=1; args+=("$1"); shift ;;
    --dry-run) light=1; args+=("$1"); shift ;;
    *) args+=("$1"); shift ;;
  esac
done
if [[ -f "$config" ]]; then
  source "$config"
elif [[ $light == 0 ]]; then
  echo "ERROR: Configuration not found: $config" >&2
  echo 'Copy fpga/build.env.example.sh to fpga/build.env.sh or use --env FILE.' >&2
  exit 2
fi
tmux_mode="${cli_tmux_mode:-${FPGA_TMUX_MODE:-auto}}"
session="${cli_session:-${FPGA_TMUX_SESSION:-}}"
case "$tmux_mode" in
  auto|off|detached) ;;
  *) echo 'ERROR: FPGA_TMUX_MODE must be auto, off or detached' >&2; exit 2 ;;
esac
if [[ $help == 1 ]]; then
  cat <<'HELP'
Terminal options handled by build.sh:
  --env FILE       Source a site configuration file.
  --tmux           Use automatic tmux protection (the default).
  --detach         Start a dedicated tmux session in the background.
  --no-tmux        Run directly and return the build exit code.
  --session NAME   Name a dedicated session; existing names are refused.
Inside tmux, automatic mode runs directly unless --session is specified.
Help and dry-run do not start tmux or load vendor setup scripts.

HELP
fi
if [[ $light == 0 && $tmux_mode != off ]] &&
   { [[ -z "${TMUX:-}" ]] || [[ $tmux_mode == detached ]] || [[ -n "$session" ]]; }; then
  tmux_bin="$(command -v "${FPGA_TMUX_BIN:-tmux}")" || {
    echo 'ERROR: tmux not found. Configure FPGA_TMUX_BIN or explicitly use --no-tmux.' >&2
    exit 2
  }
  session="${session:-fpga-$(date -u +%Y%m%d-%H%M%S)-$$}"
  if [[ ! "$session" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; then
    echo 'ERROR: Session names must use 1..64 letters, digits, underscores or hyphens.' >&2
    exit 2
  fi
  if "$tmux_bin" has-session -t "=$session" 2>/dev/null; then
    printf 'ERROR: Session already exists: %s. Attach to it or choose another name.\n' "$session" >&2
    exit 2
  fi
  config="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$config")"
  session_root="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${FPGA_TMUX_ROOT:-$root/.fpga/tmux}")"
  session_dir="$(umask 077; mkdir -p "$session_root"; mktemp -d "$session_root/${session}-XXXXXXXX")"
  launcher="$session_dir/launch.sh"
  bash_bin="$(command -v bash)"
  (
    umask 077
    {
      printf '#!/usr/bin/env bash\nset -o pipefail\n'
      # Preserve client settings even when a long-lived tmux server has an old
      # environment. The private launcher is kept under the ignored build tree.
      while IFS= read -r name; do
        case "$name" in
          FPGA_*|BAMBU_HLS|BAMBU_HLS_BACKEND_PATH|PATH|PYTHONPATH|LD_LIBRARY_PATH|LIBRARY_PATH|CPATH|PKG_CONFIG_PATH|TMPDIR|CCACHE_DISABLE|XILINX_VIVADO|XILINX_VITIS|XILINX_XRT|XILINXD_LICENSE_FILE|LM_LICENSE_FILE|SNPSLMD_LICENSE_FILE|LANG|LC_ALL)
            printf 'export %s=%q\n' "$name" "${!name}" ;;
        esac
      done < <(compgen -e)
      printf 'cd %q || exit 2\n' "$PWD"
      printf 'tmux_bin=%q\nstatus_file=%q\n' "$tmux_bin" "$session_dir/exit-code"
      cat <<'LAUNCH'
window_id="$("$tmux_bin" display-message -p -t "$TMUX_PANE" '#{window_id}')" || exit 2
"$tmux_bin" set-option -w -t "$window_id" remain-on-exit on || exit 2
LAUNCH
      printf '%q %q --env %q --no-tmux' "$bash_bin" "$root/fpga/build.sh" "$config"
      if ((${#args[@]})); then printf ' %q' "${args[@]}"; fi
      cat <<'LAUNCH'

status=$?
printf '%s\n' "$status" > "$status_file"
printf '\nBuild command exited with status %s.\n' "$status"
printf 'Exit status file: %s\n' "$status_file"
exit "$status"
LAUNCH
    } > "$launcher"
    chmod 700 "$launcher"
  )
  launch_command="$(python3 -c 'import shlex,sys; print("exec " + shlex.join(sys.argv[1:]))' "$bash_bin" "$launcher")"
  "$tmux_bin" new-session -d -s "$session" -c "$PWD" "$launch_command"
  printf 'Started tmux session: %s\n' "$session"
  printf 'Attach: %q attach-session -t %q\n' "$tmux_bin" "$session"
  printf 'Exit status file: %s\n' "$session_dir/exit-code"
  printf 'Detach with Ctrl+B, then D.\n'
  if [[ $tmux_mode == detached || -n "${TMUX:-}" || ! -t 0 || ! -t 1 ]]; then
    exit 0
  fi
  exec "$tmux_bin" attach-session -t "$session"
fi
if [[ $light == 0 ]]; then
  # Vendor setup scripts may reference unset shell variables.
  for setup in "${FPGA_BAMBU_SETTINGS:-}" "${FPGA_VIVADO_SETTINGS:-}" "${FPGA_VITIS_SETTINGS:-}"; do
    [[ -n "$setup" ]] || continue
    [[ -f "$setup" ]] || { echo "ERROR: Setup script not found: $setup" >&2; exit 2; }
    source "$setup"
  done
  if [[ -n "${FPGA_CLANG_BIN:-}" ]]; then
    export PATH="$FPGA_CLANG_BIN:$PATH"
  fi
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
export GIT_OPTIONAL_LOCKS=0
exec python3 "$root/fpga/build.py" "${args[@]}"
