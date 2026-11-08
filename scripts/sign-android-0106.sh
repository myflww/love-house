#!/usr/bin/env bash
set -eu

# Existing local tools and ORIGINAL key only. No eval, password flags, key
# generation, network call, automatic upload or device installation.
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
manifest="$script_dir/../Android-0106-signing-input.json"
output_dir="$script_dir/../signed-0106"
python_bin="python3"
java_bin=""
source_commit=""
build_tools=""
keystore=""
key_alias=""

usage() {
    printf '%s\n' 'Usage: bash scripts/sign-android-0106.sh --expected-source-commit COMMIT --build-tools SDK_BUILD_TOOLS --keystore ORIGINAL_KEYSTORE --alias EXISTING_ALIAS [--manifest FILE] [--output-dir NEW_DIRECTORY] [--python PYTHON_EXECUTABLE] [--java JAVA_EXECUTABLE]'
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --expected-source-commit|--build-tools|--keystore|--alias|--manifest|--output-dir|--python|--java)
            if [ "$#" -lt 2 ]; then usage >&2; exit 2; fi
            case "$1" in
                --expected-source-commit) source_commit="$2" ;;
                --build-tools) build_tools="$2" ;;
                --keystore) keystore="$2" ;;
                --alias) key_alias="$2" ;;
                --manifest) manifest="$2" ;;
                --output-dir) output_dir="$2" ;;
                --python) python_bin="$2" ;;
                --java) java_bin="$2" ;;
            esac
            shift 2 ;;
        *) usage >&2; exit 2 ;;
    esac
done

if [ -z "$source_commit" ] || [ -z "$build_tools" ] || [ -z "$keystore" ] || [ -z "$key_alias" ]; then
    usage >&2
    exit 2
fi

arguments=(-B "$script_dir/sign_android_0106.py" --manifest "$manifest"
    --expected-source-commit "$source_commit" --build-tools "$build_tools"
    --keystore "$keystore" --alias "$key_alias" --output-dir "$output_dir")
if [ -n "$java_bin" ]; then arguments+=(--java "$java_bin"); fi
printf '%s\n' 'Verify the original-key handoff. Python requests hidden passwords; do not put passwords in command arguments.'
exec "$python_bin" "${arguments[@]}"
