#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/kaeser-sosae/localvolts"
TMP_DIR="/tmp/localvolts"
DEST="/home/pi/homeassistant/custom_components/localvolts"
CONTAINER_NAME="homeassistant"  # adjust if your container is named differently

echo "Cloning to ${TMP_DIR}..."
rm -rf "${TMP_DIR}"
git clone --depth=1 "${REPO_URL}" "${TMP_DIR}"

echo "Copying custom_components/localvolts to ${DEST}..."
mkdir -p "$(dirname "${DEST}")"
rm -rf "${DEST}"
cp -r "${TMP_DIR}/custom_components/localvolts" "${DEST}"

echo "Cleaning up ${TMP_DIR}..."
rm -rf "${TMP_DIR}"

echo "Restarting Home Assistant container (${CONTAINER_NAME})..."
docker restart "${CONTAINER_NAME}"

echo "Done."