import subprocess
from subprocess import run

RUN_KWARGS = {
    "check": True,
    "capture_output": True,
    "stdout": subprocess.PIPE,
    "stderr"=STDOUT
}

def handle_completed_process(func):
    @wrapper
    inner():
        result = func(*args, **kwargs)
        for line in result.

def up(path)
    return run('docker-compose up -d {}'.format(path), **RUN_KWARGS)

def down(path, check=True):
    return run('docker-compose down -d {}'.format(path), **RUN_KWARGS)

def restart(container_name, check=True):
    return run('docker restart {}'.format(container_name), **RUN_KWARGS)
