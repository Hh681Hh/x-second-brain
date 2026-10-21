"""Per-user, windowless Windows logon supervisor; no elevated rights or secrets."""
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time

import httpx

from .agent_cli import running, start
from .config import Settings
from .security import UserError


def acquire_lock(path):
    """Keep the file handle alive; Windows releases the lock even after a crash."""
    import msvcrt
    handle = path.open('a+b')
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def ensure_service(settings):
    # Timeouts/authentication errors are not proof the process has exited.
    # Only agent_cli.running's explicit ConnectError result can trigger start.
    current = running(settings)
    if current is not None:
        return False
    start(settings, setup=False, engine='codex')
    return True


def main():
    if os.name != 'nt':
        raise SystemExit('This logon supervisor is for Windows only.')
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    enabled = settings.data_dir / 'autostart.enabled'
    if not enabled.exists():
        return
    lock = acquire_lock(settings.data_dir / 'autostart.lock')
    if lock is None:
        return
    # pythonw has no console streams. Agent startup messages go to the log too.
    output = (settings.data_dir / 'autostart-console.log').open('w', encoding='utf-8')
    sys.stdout = sys.stderr = output
    handler = RotatingFileHandler(settings.data_dir / 'autostart.log', maxBytes=500_000,
                                  backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger = logging.getLogger('xsb.autostart')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.info('Logon supervisor started pid=%s', os.getpid())
    try:
        while enabled.exists():
            try:
                if ensure_service(settings):
                    logger.info('Local knowledge service started successfully')
            except (httpx.HTTPError, UserError, OSError, ValueError):
                # Do not log headers, configuration, or possibly sensitive responses.
                logger.warning('Service unavailable or not identifiable; retry in 30 seconds')
            output.flush()
            for _ in range(30):
                if not enabled.exists():
                    return
                time.sleep(1)
    finally:
        logger.info('Logon supervisor stopped')
        lock.close()
        output.close()


if __name__ == '__main__':
    main()
