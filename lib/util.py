import os
import shutil
import string
import tempfile
from threading import Timer
import subprocess

def memoize(f):
    rets = {}

    def wrap(*args):
        if not args in rets:
            rets[args] = f(*args)

        return rets[args]

    wrap.__name__ = f.__name__
    return wrap

def climb(top):
    right = True
    while right:
        top, right = os.path.split(top)
        yield top

@memoize
def find(top, name, parent=False):
    for d in climb(top):
        target = os.path.join(d, name)
        if os.path.exists(target):
            if parent:
                return d

            return target

def extract_path(cmd, delim=':'):
    path = popen(cmd, os.environ).communicate()[0].decode()
    path = path.split('__SUBL__', 1)[1].strip('\r\n')
    return ':'.join(path.split(delim))

def find_path(env):
    # find PATH using shell --login
    if 'SHELL' in env:
        shell_path = env['SHELL']
        shell = os.path.basename(shell_path)

        if shell in ('bash', 'zsh'):
            return extract_path(
                (shell_path, '--login', '-c', 'echo __SUBL__$PATH')
            )
        elif shell == 'fish':
            return extract_path(
                (shell_path, '--login', '-c', 'echo __SUBL__; for p in $PATH; echo $p; end'),
                '\n'
            )

    # guess PATH if we haven't returned yet
    split = env['PATH'].split(':')
    p = env['PATH']
    for path in (
        '/usr/bin', '/usr/local/bin',
        '/usr/local/php/bin', '/usr/local/php5/bin'
                ):
        if not path in split:
            p += (':' + path)

    return p

@memoize
def create_environment():
    if os.name == 'posix':
        os.environ['PATH'] = find_path(os.environ)

    return os.environ

def can_exec(fpath):
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

def which(cmd):
    env = create_environment()
    for base in env.get('PATH', '').split(os.pathsep):
        path = os.path.join(base, cmd)
        if can_exec(path):
            return path
        if os.name == 'nt':
            if not cmd.endswith('.exe') and can_exec(path + '.exe'):
                return path + '.exe'

    return None

def touch(path):
    with open(path, 'a'):
        os.utime(path, None)

# popen methods
def combine_output(out, sep=''):
    return sep.join((
        (out[0].decode('utf8') or ''),
        (out[1].decode('utf8') or ''),
    ))

def communicate(cmd, stdin=None, timeout=None, **popen_args):
    p = popen(cmd, **popen_args)
    if isinstance(p, subprocess.Popen):
        timer = None
        if timeout is not None:
            kill = lambda: p.kill()
            timer = Timer(timeout, kill)
            timer.start()

        out = p.communicate(stdin)
        if timer is not None:
            timer.cancel()

        return combine_output(out)
    elif isinstance(p, str):
        return p
    else:
        return ''

def tmpfile(cmd, code, suffix=''):
    if isinstance(cmd, str):
        cmd = cmd,

    f = tempfile.NamedTemporaryFile(suffix=suffix)
    f.write(code.encode('utf8'))
    f.flush()

    cmd = tuple(cmd) + (f.name,)
    out = popen(cmd)
    if out:
        out = out.communicate()
        return combine_output(out)
    else:
        return ''

def tmpdir(cmd, files, filename, code):
    filename = os.path.split(filename)[1]
    d = tempfile.mkdtemp()

    for f in files:
        try: os.makedirs(os.path.join(d, os.path.split(f)[0]))
        except: pass

        target = os.path.join(d, f)
        if os.path.split(target)[1] == filename:
            # source file hasn't been saved since change, so update it from our live buffer
            f = open(target, 'wb')
            f.write(code)
            f.close()
        else:
            shutil.copyfile(f, target)

    os.chdir(d)
    out = popen(cmd)
    if out:
        out = out.communicate()
        out = combine_output(out, '\n')

        # filter results from build to just this filename
        # no guarantee all languages are as nice about this as Go
        # may need to improve later or just defer to communicate()
        out = '\n'.join([
            line for line in out.split('\n') if filename in line.split(':', 1)[0]
        ])
    else:
        out = ''

    shutil.rmtree(d, True)
    return out

def popen(cmd, env=None, use_pty=False):
    if isinstance(cmd, str):
        cmd = cmd,

    stdin = subprocess.PIPE
    stdout = subprocess.PIPE
    stderr = subprocess.PIPE

    master = None
    info = None
    if os.name == 'nt':
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
    elif use_pty:
        import pty
        master, slave = pty.openpty()
        stdin = slave
        stdout = slave

    if env is None:
        env = create_environment()

    try:
        p = subprocess.Popen(cmd, stdin=stdin,
            stdout=stdout, stderr=stderr,
            startupinfo=info, env=env)

        if master:
            p.pty = True
            p.stdout = os.fdopen(master, 'rb')
            p.stdin = os.fdopen(master, 'wb')
        else:
            p.pty = False

        return p
    except OSError as err:
        print('Error launching', repr(cmd))
        print('Error was:', err.strerror)
        print('Environment:', env)
        return err.strerror

def get_windows_drives():
    from ctypes import windll
    bitmask = windll.kernel32.GetLogicalDrives()
    return [c for i, c in enumerate(string.ascii_uppercase) if bitmask & 1 << i]
