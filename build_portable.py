"""Copy an installed Windows Python and its app dependencies into runtime/."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import struct
import sys


PROJECT = Path(__file__).resolve().parent
DEPENDENCIES = ('numpy', 'scipy', 'joblib', 'cloudpickle', 'threadpoolctl', 'scikit-learn',
                'cryptography', 'cffi', 'pycparser', 'qrcode', 'pillow')


def main():
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        raise SystemExit('Build with 64-bit Python 3.12 on Windows.')
    python = Path(sys.base_prefix)
    runtime = PROJECT/'runtime'
    tree_ignore = shutil.ignore_patterns('__pycache__', '*.pyc', 'site-packages')
    packages = [distribution(name) for name in DEPENDENCIES]
    for folder in ('DLLs', 'Lib', 'tcl'):
        if not (python/folder).is_dir():
            raise SystemExit('Use the full Python installation with Tkinter.')
        shutil.copytree(python/folder, runtime/folder, dirs_exist_ok=True, ignore=tree_ignore)
    for source in python.iterdir():
        if source.name in ('python.exe', 'pythonw.exe', 'LICENSE.txt') or source.suffix.lower() == '.dll':
            shutil.copy2(source, runtime/source.name)

    target = runtime/'Lib/site-packages'
    for package in packages:
        for source in package.files or ():
            relative = Path(source)
            if '..' in relative.parts or '__pycache__' in relative.parts or relative.suffix in ('.pyc', '.whl'):
                continue
            installed = package.locate_file(source)
            if installed.is_file():
                destination = target/relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(installed, destination)
    print(f'Bundled Python and app dependencies in {runtime}')


if __name__ == '__main__':
    main()
