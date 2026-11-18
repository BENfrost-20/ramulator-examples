#!/usr/bin/env bash
# Move a release bundle through the Mac with one VPN connected at a time.
set -euo pipefail
umask 077
root="$(cd -- "$(dirname -- "$0")" && pwd)"
config="${FPGA_DEPLOY_CONFIG:-$root/deploy.env}"
if [[ $# -gt 0 && $1 == --config && $# -ge 2 ]]; then
    config="$2"
    shift 2
fi
if [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]; then
    echo 'Usage: fpga/transfer.sh [--config FILE] {pull|push} BUNDLE.tar.gz'
    echo 'pull uses the Ferrandi VPN. push uses the ETH VPN.'
    exit 0
fi
if [[ $# != 2 || ! $2 =~ ^[[:alnum:]][[:alnum:]_.-]*\.tar\.gz$ ]]; then
    echo 'Usage: fpga/transfer.sh [--config FILE] {pull|push} BUNDLE.tar.gz' >&2
    exit 2
fi
action="$1"
name="$2"
if [[ ! -f "$config" ]]; then
    printf 'Configure deployment paths in %s using deploy.env.example.\n' "$config" >&2
    exit 2
fi
source "$config"
: "${FPGA_MAC_ARTIFACT_DIR:?Set FPGA_MAC_ARTIFACT_DIR in the deployment config}"
local_file="$FPGA_MAC_ARTIFACT_DIR/$name"

# Quote values for the shell started by SSH; paths may contain spaces.
quote() {
    local value="$1"
    printf '%s' "'"
    while [[ "$value" == *"'"* ]]; do
        printf '%s' "${value%%\'*}" "'\\''"
        value="${value#*\'}"
    done
    printf '%s' "$value" "'"
}

case "$action" in
    pull)
        : "${FPGA_FERRANDI_SSH:?Set FPGA_FERRANDI_SSH}"
        : "${FPGA_FERRANDI_ARTIFACT_DIR:?Set FPGA_FERRANDI_ARTIFACT_DIR}"
        mkdir -p -- "$FPGA_MAC_ARTIFACT_DIR"
        if [[ -e "$local_file" || -L "$local_file" ]]; then
            printf 'Bundle already exists: %s\n' "$local_file" >&2
            exit 2
        fi
        staging="$(mktemp "$FPGA_MAC_ARTIFACT_DIR/.pull.XXXXXXXX")"
        trap 'rm -f -- "$staging"' EXIT
        scp -- "$FPGA_FERRANDI_SSH:$FPGA_FERRANDI_ARTIFACT_DIR/$name" "$staging"
        ln -- "$staging" "$local_file"
        printf 'Bundle on the Mac: %s\n' "$local_file"
        ;;
    push)
        : "${FPGA_HACC_SSH:?Set FPGA_HACC_SSH}"
        : "${FPGA_HACC_ARTIFACT_DIR:?Set FPGA_HACC_ARTIFACT_DIR}"
        expected="$(shasum -a 256 < "$local_file")"
        read -r -d '' receiver <<'BASH' || true
set -euo pipefail
umask 077
directory="$1"
name="$2"
expected="$3"
mkdir -p -- "$directory"
staging="$(mktemp "$directory/.upload.XXXXXXXX")"
trap 'rm -f -- "$staging"' EXIT
cat > "$staging"
actual="$(sha256sum < "$staging")"
if [[ ${actual%% *} != "$expected" ]]; then
    echo 'Upload checksum mismatch.' >&2
    exit 2
fi
if [[ -e "$directory/$name" || -L "$directory/$name" ]]; then
    printf 'Bundle already exists: %s\n' "$directory/$name" >&2
    exit 2
fi
ln -- "$staging" "$directory/$name"
printf 'Bundle on HACC: %s\n' "$directory/$name"
BASH
        ssh -- "$FPGA_HACC_SSH" \
            "bash -c $(quote "$receiver") -- $(quote "$FPGA_HACC_ARTIFACT_DIR") $(quote "$name") $(quote "${expected%% *}")" \
            < "$local_file"
        ;;
    *)
        echo 'Choose pull or push.' >&2
        exit 2
        ;;
esac
