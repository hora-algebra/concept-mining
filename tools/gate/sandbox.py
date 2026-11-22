"""Run a command in a bubblewrap sandbox: no network, empty environment, and
only the given directories visible (writable ones explicitly listed).

Lean runs code while it compiles, so everything that compiles or loads the
pull request's Lean runs through `run()`. The guard (tools/gate/guard.py)
already refuses compile-time code; the sandbox is the second wall: even code
that got past the guard cannot reach the network, a token, the trusted
checkout or the gate's output files.

On a machine without bubblewrap (a contributor's Mac) the command runs
directly only when GATE_ALLOW_NO_SANDBOX=1; CI never sets it.
"""

from __future__ import annotations

import os
import shutil
import subprocess


class SandboxError(RuntimeError):
    pass


SYSTEM_RO = ["/usr", "/etc/alternatives", "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d",
             "/etc/passwd", "/etc/group", "/etc/nsswitch.conf", "/etc/localtime"]
TOP_LINKS = ["/bin", "/sbin", "/lib", "/lib64", "/lib32"]


def available() -> bool:
    return shutil.which("bwrap") is not None


def argv(cmd: list[str], *, cwd: str, rw: list[str], ro: list[str], elan_home: str,
         env: dict | None = None) -> list[str]:
    a = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
         "--setenv", "PATH", f"{elan_home}/bin:/usr/local/bin:/usr/bin:/bin",
         "--setenv", "HOME", "/tmp/home", "--setenv", "ELAN_HOME", elan_home,
         "--setenv", "LANG", "C.UTF-8",
         "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/tmp/home"]
    for k, v in (env or {}).items():
        a += ["--setenv", k, v]
    for p in TOP_LINKS:
        if os.path.islink(p):
            a += ["--symlink", os.readlink(p), p]
        elif os.path.isdir(p):
            a += ["--ro-bind", p, p]
    for p in SYSTEM_RO:
        a += ["--ro-bind-try", p, p]
    a += ["--ro-bind", elan_home, elan_home]
    # later binds win: writable roots first, read-only sub-directories after
    for p in rw:
        a += ["--bind", p, p]
    for p in ro:
        a += ["--ro-bind", p, p]
    a += ["--chdir", cwd, "--"]
    return a + cmd


def run(cmd: list[str], *, cwd: str, rw: list[str] = (), ro: list[str] = (), timeout: int | None = None,
        elan_home: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    elan_home = elan_home or os.environ.get("ELAN_HOME") or os.path.expanduser("~/.elan")
    if not available():
        if os.environ.get("GATE_ALLOW_NO_SANDBOX") == "1":
            return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                                  env=dict(os.environ, **(env or {})))
        raise SandboxError("bubblewrap (bwrap) is not installed; refusing to run Lean outside a sandbox")
    return subprocess.run(argv(cmd, cwd=cwd, rw=list(rw), ro=list(ro), elan_home=elan_home, env=env),
                          capture_output=True, text=True, timeout=timeout)


SELF_TEST = r"""
import os, socket, sys
bad = []
try:
    socket.create_connection(("1.1.1.1", 53), 3).close(); bad.append("network reachable")
except OSError:
    pass
for k in os.environ:
    if k.startswith(("GITHUB_", "ACTIONS_", "RUNNER_", "GH_", "OPENAI", "ANTHROPIC")) or "TOKEN" in k:
        bad.append("environment variable " + k)
for p in sys.argv[1:]:
    if os.path.exists(p):
        bad.append("visible: " + p)
print("\n".join(bad) or "ok")
sys.exit(1 if bad else 0)
"""


def self_test(*, cwd: str, rw: list[str], ro: list[str], hidden: list[str], elan_home: str | None = None) -> None:
    """Fail closed unless the sandbox really hides the network, the
    environment and the given paths (e.g. the trusted checkout)."""
    if not available():
        if os.environ.get("GATE_ALLOW_NO_SANDBOX") == "1":
            return
        raise SandboxError("bubblewrap (bwrap) is not installed")
    # the system interpreter: the one from setup-python lives outside the sandbox
    r = run(["/usr/bin/python3", "-I", "-c", SELF_TEST, *hidden], cwd=cwd, rw=rw, ro=ro, timeout=60, elan_home=elan_home)
    if r.returncode != 0 or r.stdout.strip() != "ok":
        raise SandboxError("sandbox self-test failed: " + (r.stdout + r.stderr).strip()[:500])
    # writes outside the writable roots must fail
    r = run(["/bin/sh", "-c", "touch /usr/.gate-probe 2>/dev/null && echo writable || echo ok"],
            cwd=cwd, rw=rw, ro=ro, timeout=60, elan_home=elan_home)
    if r.stdout.strip() != "ok":
        raise SandboxError("sandbox self-test failed: /usr is writable")
