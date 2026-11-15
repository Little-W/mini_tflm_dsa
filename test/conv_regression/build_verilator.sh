#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Local, non-root build of the fixed official Verilator release.
# Build only release executables: compiling Verilator's debug binary is optional.
set -euo pipefail
CONV_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_ROOT="${WORK_ROOT:-$CONV_REPO_ROOT/build/toolchain/verilator-5.054-work}"
PREFIX="${PREFIX:-$CONV_REPO_ROOT/build/toolchain/verilator-5.054}"
JOBS="${JOBS:-2}"
VERILATOR_COMMIT="e4c94116fafb093ce153c9d2f295d3b1f0725bab"
case "$WORK_ROOT $PREFIX" in *$'\n'*) echo 'Paths must not contain newlines' >&2; exit 2;; esac
for program in git curl sha256sum tar gcc g++ make perl python3; do
    command -v "$program" >/dev/null || { echo "Missing prerequisite: $program" >&2; exit 2; }
done
mkdir -p "$WORK_ROOT/downloads" "$WORK_ROOT/dependency_sources" "$WORK_ROOT/logs" "$PREFIX"
WORK_ROOT="$(cd "$WORK_ROOT" && pwd)"
PREFIX="$(cd "$PREFIX" && pwd)"
case "$WORK_ROOT" in *' '*) echo 'Verilator build path must not contain spaces' >&2; exit 2;; esac
DEPS="$WORK_ROOT/dependencies"
export PATH="$DEPS/bin:$PATH"
unset VERILATOR_ROOT

fetch() {
    local filename="$1" url="$2" expected="$3"
    if [[ ! -f "$WORK_ROOT/downloads/$filename" ]]; then
        curl --fail --location --connect-timeout 15 --max-time 300 \
            --output "$WORK_ROOT/downloads/$filename" "$url"
    fi
    printf '%s  %s\n' "$expected" "$WORK_ROOT/downloads/$filename" | sha256sum --check
}

dependency() {
    local name="$1" archive="$2"
    shift 2
    if [[ ! -d "$WORK_ROOT/dependency_sources/$name" ]]; then
        tar -xf "$WORK_ROOT/downloads/$archive" -C "$WORK_ROOT/dependency_sources"
    fi
    (
        cd "$WORK_ROOT/dependency_sources/$name"
        ./configure --prefix="$DEPS" "$@"
        make -j "$JOBS"
        make install
    ) > "$WORK_ROOT/logs/$name.log" 2>&1
}

# Official GNU / flex release tarballs, verified against the downloaded artifacts
# used in this task. These tools are installed below WORK_ROOT, without sudo.
fetch m4-1.4.19.tar.xz https://ftp.gnu.org/gnu/m4/m4-1.4.19.tar.xz \
    63aede5c6d33b6d9b13511cd0be2cac046f2e70fd0a07aa9573a04a82783af96
fetch autoconf-2.72.tar.xz https://ftp.gnu.org/gnu/autoconf/autoconf-2.72.tar.xz \
    ba885c1319578d6c94d46e9b0dceb4014caafe2490e437a0dbca3f270a223f5a
fetch bison-3.8.2.tar.xz https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz \
    9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2
fetch flex-2.6.4.tar.gz https://github.com/westes/flex/releases/download/v2.6.4/flex-2.6.4.tar.gz \
    e87aae032bf07c26f85ac0ed3250998c37621d95f8bd748b31f15b33c45ee995
fetch help2man-1.49.3.tar.xz https://ftp.gnu.org/gnu/help2man/help2man-1.49.3.tar.xz \
    4d7e4fdef2eca6afe07a2682151cea78781e0a4e8f9622142d9f70c083a2fd4f
dependency m4-1.4.19 m4-1.4.19.tar.xz
dependency autoconf-2.72 autoconf-2.72.tar.xz
dependency bison-3.8.2 bison-3.8.2.tar.xz --disable-nls
dependency flex-2.6.4 flex-2.6.4.tar.gz --disable-nls
dependency help2man-1.49.3 help2man-1.49.3.tar.xz --disable-nls

SRC="$WORK_ROOT/verilator"
if [[ ! -e "$SRC" ]]; then
    git init "$SRC"
    git -C "$SRC" remote add origin https://github.com/verilator/verilator.git
    git -C "$SRC" fetch --depth 1 origin "$VERILATOR_COMMIT"
    git -C "$SRC" checkout --detach FETCH_HEAD
fi
[[ "$(git -C "$SRC" rev-parse HEAD)" == "$VERILATOR_COMMIT" ]] || {
    echo 'Existing source tree does not match the fixed Verilator commit' >&2; exit 2;
}
git -C "$SRC" diff --exit-code --quiet || { echo 'Source tree has local edits' >&2; exit 2; }
git -C "$SRC" rev-parse HEAD > "$WORK_ROOT/source_commit.txt"
(
    cd "$SRC"
    autoconf
    ./configure --prefix="$PREFIX"
    make -C src -j "$JOBS" opt
    make install-all VL_INST_PUBLIC_BIN_FILES='verilator_bin verilator_coverage_bin'
) > "$WORK_ROOT/logs/verilator_release_build.log" 2>&1
"$PREFIX/bin/verilator" --version | tee "$WORK_ROOT/installed_version.txt"
mkdir -p "$WORK_ROOT/smoke"
cat > "$WORK_ROOT/smoke/smoke.sv" <<'SV'
module smoke;
  logic [7:0] a;
  initial begin
    a=8'd41; #1;
    assert(a+8'd1==8'd42) else $fatal(1,"smoke failed");
    $display("VERILATOR_OFFICIAL_SOURCE_SMOKE_PASS");
    $finish;
  end
endmodule
SV
"$PREFIX/bin/verilator" --binary --timing --assert -CFLAGS -std=c++20 \
    --top-module smoke --Mdir "$WORK_ROOT/smoke/obj" "$WORK_ROOT/smoke/smoke.sv" \
    > "$WORK_ROOT/logs/smoke_build.log" 2>&1
"$WORK_ROOT/smoke/obj/Vsmoke" | tee "$WORK_ROOT/logs/smoke_run.log"
printf 'Use: export PATH="%s/bin:$PATH"\n' "$PREFIX"
