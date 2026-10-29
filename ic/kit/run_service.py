"""Start one service process with a chosen release.

Run: python -m ic.kit.run_service --system bank --component payments --version 1.3 --data runs/bank-8100

The release is found in the copy's releases.json (for releases added later, for
example by a fault) or at targets/<system>/releases/<component>/v<version>.py.
"""

import argparse
import importlib.util
import os
import sys

from .store import Releases, read_json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def release_path(system, component, image, version, data_dir):
    """Where a release's code lives. `image` names the release folder; a standby shares its primary's."""
    registered = Releases(data_dir).module_path(component, version)
    if registered:
        return registered
    name = "v" + version.replace(".", "_") + ".py"
    return os.path.join(ROOT, "targets", system, "releases", image, name)


def load_release(system, component, image, version, data_dir):
    path = release_path(system, component, image, version, data_dir)
    if not os.path.exists(path):
        raise SystemExit(f"no release module for {component} {version} at {path}")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    module_name = f"_release_{system}_{component}_{version.replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.Release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", required=True)
    parser.add_argument("--component", required=True)
    parser.add_argument("--image", help="release folder name; defaults to the component name")
    parser.add_argument("--version", required=True)
    parser.add_argument("--data", required=True)
    args = parser.parse_args()
    state = read_json(os.path.join(args.data, "ports.json"), {})
    release_cls = load_release(args.system, args.component, args.image or args.component, args.version, args.data)
    ctx = {"system": args.system, "component": args.component, "version": args.version,
           "data_dir": args.data, "port": state["ports"][args.component], "ports": state["ports"],
           "admin_token": os.environ.get("IC_ADMIN_TOKEN", "")}
    release_cls(ctx).serve()


if __name__ == "__main__":
    main()
