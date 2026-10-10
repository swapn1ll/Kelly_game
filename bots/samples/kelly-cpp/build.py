"""Compiles bot.cpp into ./bot (bot.exe on Windows).

Works on Mac, Linux and Windows. The referee runs it once before the tournament
(untimed), and again only when your files change. You can also run it yourself:
    python3 build.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
exe = here / ('bot.exe' if os.name == 'nt' else 'bot')
sources = ['bot.cpp']

for cxx in (os.environ.get('CXX'), 'c++', 'g++', 'clang++'):
    if cxx and shutil.which(cxx):
        cmd = [cxx, '-std=c++17', '-O2', *sources, '-o', str(exe)]
        break
else:
    if shutil.which('cl'):                      # Visual Studio's compiler (Developer Command Prompt)
        cmd = ['cl', '/nologo', '/std:c++17', '/O2', '/EHsc', *sources, f'/Fe:{exe}']
    else:
        sys.exit('No C++ compiler found. Mac: run  xcode-select --install.  '
                 'Windows: install MinGW-w64 (g++) or Visual Studio Build Tools.  Linux: install g++.')

sys.exit(subprocess.run(cmd, cwd=here).returncode)
