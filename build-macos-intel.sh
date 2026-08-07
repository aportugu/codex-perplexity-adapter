#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h}"
release_tag="20260805"
python_version="3.12.13"
archive_name="cpython-${python_version}+${release_tag}-x86_64-apple-darwin-install_only.tar.gz"
release_url="https://github.com/astral-sh/python-build-standalone/releases/download/${release_tag}"
download_dir="${project_dir}/build/downloads"
archive_path="${download_dir}/${archive_name}"
checksums_path="${download_dir}/SHA256SUMS-${release_tag}"
toolchain_dir="${project_dir}/build/toolchains/python-${python_version}-${release_tag}-x86_64"
intel_python="${toolchain_dir}/bin/python3"
intel_venv="${project_dir}/build/toolchains/adapter-x86_64-venv"
intel_pyinstaller="${intel_venv}/bin/pyinstaller"

mkdir -p "${download_dir}" "${project_dir}/build/toolchains"

if [[ ! -f "${archive_path}" ]]; then
  curl --fail --location --retry 3 \
    "${release_url}/${archive_name//+/%2B}" \
    --output "${archive_path}"
fi

curl --fail --location --retry 3 \
  "${release_url}/SHA256SUMS" \
  --output "${checksums_path}"

expected_sha="$(awk -v filename="${archive_name}" '$2 == filename || $2 == "*" filename { print $1; exit }' "${checksums_path}")"
if [[ -z "${expected_sha}" ]]; then
  print -u2 "No checksum found for ${archive_name}"
  exit 1
fi

actual_sha="$(shasum -a 256 "${archive_path}" | awk '{ print $1 }')"
if [[ "${actual_sha}" != "${expected_sha}" ]]; then
  print -u2 "Checksum verification failed for ${archive_name}"
  exit 1
fi

if [[ ! -x "${intel_python}" ]]; then
  rm -rf "${toolchain_dir}"
  mkdir -p "${toolchain_dir}"
  tar -xzf "${archive_path}" --strip-components=1 -C "${toolchain_dir}"
fi

if [[ ! -x "${intel_venv}/bin/python" ]]; then
  rm -rf "${intel_venv}"
  arch -x86_64 "${intel_python}" -m venv "${intel_venv}"
fi

arch -x86_64 "${intel_venv}/bin/python" -m pip install --upgrade pip
arch -x86_64 "${intel_venv}/bin/python" -m pip install "${project_dir}" "pyinstaller==6.21.0"

ADAPTER_TARGET_ARCH=x86_64 \
ADAPTER_PYINSTALLER="${intel_pyinstaller}" \
arch -x86_64 "${project_dir}/build-macos-app.sh"
