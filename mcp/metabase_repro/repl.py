"""Socket REPL client for evaluating Clojure code against a running Metabase instance."""
from __future__ import annotations

import socket
import time

from .core import read_state_file


def repl_eval(repro_dir: str, code: str, timeout: int = 30) -> str:
    """Send Clojure code to the socket REPL and return the result."""
    port_str = read_state_file(repro_dir, "port")
    if not port_str:
        return "ERROR: No port file found. Is Metabase running?"
    repl_port = int(port_str) + 3000

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("127.0.0.1", repl_port))

        # Read initial prompt (e.g. "user=> ")
        _read_until_prompt(sock, timeout)

        # Send code
        sock.sendall((code + "\n").encode())

        # Read result until next prompt
        result = _read_until_prompt(sock, timeout)

        sock.close()
        return result.strip()
    except socket.timeout:
        return f"ERROR: Socket REPL timed out after {timeout}s"
    except ConnectionRefusedError:
        return f"ERROR: Could not connect to socket REPL on port {repl_port}"
    except Exception as e:
        return f"ERROR: {e}"


def _read_until_prompt(sock: socket.socket, timeout: int = 30) -> str:
    """Read from socket until we see a 'namespace=> ' prompt."""
    data = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            text = data.decode("utf-8", errors="replace")
            # Socket REPL prompts end with "=> "
            if text.rstrip().endswith("=>") or "=> " in text.split("\n")[-1]:
                # Strip the prompt from the result
                lines = text.split("\n")
                result_lines = []
                for line in lines:
                    if line.strip().endswith("=>"):
                        break
                    result_lines.append(line)
                return "\n".join(result_lines)
        except socket.timeout:
            continue
    return data.decode("utf-8", errors="replace")
