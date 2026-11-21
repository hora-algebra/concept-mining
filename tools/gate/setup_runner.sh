#!/bin/sh
# Prepare a GitHub-hosted Ubuntu runner for the gate's build job: free disk,
# install bubblewrap and allow it to create user namespaces, install elan
# from a pinned release with a checked digest.
set -eu
ELAN_VERSION=v4.2.4
ELAN_SHA256=42b94d4244e8353142c456ec0e4ca6528fd898a6c604d4059f494e706e431f63

# Mathlib's build cache and a CFSG build need more than the default free space
sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /opt/hostedtoolcache/CodeQL /usr/local/share/boost || true
df -h / | tail -1

sudo apt-get -qq update
sudo apt-get -qq install -y bubblewrap >/dev/null
# Ubuntu 24.04 restricts unprivileged user namespaces through AppArmor
sudo sysctl -q -w kernel.apparmor_restrict_unprivileged_userns=0 || true
bwrap --version

tmp=$(mktemp -d)
curl -sSfL -o "$tmp/elan.tar.gz" \
  "https://github.com/leanprover/elan/releases/download/$ELAN_VERSION/elan-x86_64-unknown-linux-gnu.tar.gz"
echo "$ELAN_SHA256  $tmp/elan.tar.gz" | sha256sum -c -
tar -xzf "$tmp/elan.tar.gz" -C "$tmp"
"$tmp/elan-init" -y --default-toolchain none >/dev/null
echo "$HOME/.elan/bin" >> "$GITHUB_PATH"
