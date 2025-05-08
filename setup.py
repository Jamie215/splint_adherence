import sys
from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but some might need fine-tuning
build_exe_options = {
    "include_files": ["assets/"],
    "build_exe": "Splint_Adherence",
    "includes": ["idna.idnadata"],
    "packages": ['engineio','socketio','flask_socketio','threading', 'numpy', 'pandas', 'scipy']
}

# Base can be "Win32GUI" if you're building a GUI application on Windows
base = None
if sys.platform == "win32":
    base = "Win32GUI"

executables = [
    Executable(
        "app.py",
        base=base,
        icon="Splint_Adherence_Icon.ico"
    )
]

setup(
    name="Splint_Adherence",
    version="1.0.0",
    description="Splint Adherence Measurement Application",
    options={"build_exe": build_exe_options},
    executables=executables
)
