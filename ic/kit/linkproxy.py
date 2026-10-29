"""A TCP relay that sits on a link between two services and can slow it down or drop it.

Each route listens on its own port and forwards to the real service. The fault
injector changes a route's latency or drop rate by editing links.json; the
relay re-reads it every 0.2 s. The delays are real network delays, so the
services see genuine timeouts.

Run: python -m ic.kit.linkproxy --config runs/bank-8100/links.json
"""

import argparse
import asyncio
import json
import random
import time


class Routes:
    def __init__(self, path):
        self.path = path
        self.doc = {"routes": {}}
        self.read_t = 0.0

    def get(self, name):
        if time.time() - self.read_t > 0.2:
            try:
                with open(self.path, encoding="utf-8") as handle:
                    self.doc = json.load(handle)
            except (OSError, ValueError):
                pass
            self.read_t = time.time()
        return self.doc["routes"].get(name, {})


async def pipe(reader, writer, route, routes, delay_each_chunk):
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            if delay_each_chunk:
                spec = routes.get(route)
                delay = spec.get("latency_ms", 0) + random.uniform(0, spec.get("jitter_ms", 0))
                if delay > 0:
                    await asyncio.sleep(delay / 1000)
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def relay(client_reader, client_writer, route, upstream_port, routes):
    spec = routes.get(route)
    if random.random() < spec.get("drop_pct", 0.0):
        client_writer.close()  # the link drops this connection
        return
    try:
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", upstream_port)
    except OSError:
        client_writer.close()
        return
    await asyncio.gather(
        pipe(client_reader, up_writer, route, routes, delay_each_chunk=True),
        pipe(up_reader, client_writer, route, routes, delay_each_chunk=False),
    )


async def main(config_path):
    routes = Routes(config_path)
    with open(config_path, encoding="utf-8") as config:
        doc = json.load(config)
    servers = []
    for name, spec in doc["routes"].items():
        server = await asyncio.start_server(
            lambda r, w, n=name, up=spec["upstream"]: relay(r, w, n, up, routes),
            "127.0.0.1", spec["listen"])
        servers.append(server)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.config))
    except KeyboardInterrupt:
        pass
