"""
Setup Script for Fusion 360 MCP Server

With the two-process architecture, MCP packages are NO LONGER installed
into Fusion 360's Python environment (which has code-signing restrictions
on macOS). Instead:

1. MCP packages are installed into a local venv (this script handles that)
2. The MCPserve add-in folder is installed into Fusion 360 manually

Usage:
    python install_mcp_for_fusion.py
"""

import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parent
VENV_DIR = WORKSPACE / "venv"
REQUIREMENTS = WORKSPACE / "requirements.txt"


def create_venv():
    """Create a virtual environment if it doesn't exist."""
    if VENV_DIR.exists():
        print(f"Virtual environment already exists at: {VENV_DIR}")
        return True

    print(f"Creating virtual environment at: {VENV_DIR}")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        print("Virtual environment created.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to create virtual environment: {e}")
        return False


def get_venv_python():
    """Get the path to the venv Python executable."""
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def install_requirements():
    """Install MCP packages into the venv."""
    python = get_venv_python()
    if not os.path.exists(python):
        print(f"Venv Python not found at: {python}")
        return False

    print(f"\nInstalling MCP packages using: {python}")
    try:
        result = subprocess.run(
            [python, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            capture_output=True, text=True, check=True,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Installation failed:\n{e.stdout}\n{e.stderr}")
        return False


def verify_installation():
    """Verify that MCP packages are importable."""
    python = get_venv_python()
    try:
        result = subprocess.run(
            [python, "-c", (
                "from mcp.server.fastmcp import FastMCP; "
                "import uvicorn; "
                "print('All packages verified successfully!')"
            )],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(result.stdout.strip())
            return True
        else:
            print(f"Verification failed:\n{result.stderr}")
            return False
    except Exception as e:
        print(f"Verification error: {e}")
        return False


def find_fusion_addins_folder():
    """Find the Fusion 360 add-ins folder for the current platform."""
    system = platform.system()
    if system == "Darwin":
        candidates = [
            Path.home() / "Library" / "Application Support" / "Autodesk"
            / "Autodesk Fusion" / "API" / "AddIns",
            Path.home() / "Library" / "Application Support" / "Autodesk"
            / "Autodesk Fusion 360" / "API" / "AddIns",
        ]
    elif system == "Windows":
        candidates = [
            Path(os.environ.get("APPDATA", "")) / "Autodesk"
            / "Autodesk Fusion" / "API" / "AddIns",
            Path(os.environ.get("APPDATA", "")) / "Autodesk"
            / "Autodesk Fusion 360" / "API" / "AddIns",
        ]
    else:
        return None

    for path in candidates:
        if path.exists():
            return path
    return None


def print_addin_instructions():
    """Print instructions for installing the Fusion 360 add-in."""
    addins_folder = find_fusion_addins_folder()

    print("\n" + "=" * 60)
    print("FUSION 360 ADD-IN INSTALLATION")
    print("=" * 60)

    if addins_folder:
        target = addins_folder / "MCPserve"
        source = WORKSPACE / "MCPserve"
        print(f"\nDetected Fusion 360 add-ins folder:\n  {addins_folder}")
        print(f"\nTo install the add-in, you can either:")
        print(f"\n  Option A: Create a symlink (recommended for development):")
        if platform.system() == "Windows":
            print(f'    mklink /D "{target}" "{source}"')
        else:
            print(f'    ln -s "{source}" "{target}"')
        print(f"\n  Option B: Copy the folder:")
        if platform.system() == "Windows":
            print(f'    xcopy /E /I "{source}" "{target}"')
        else:
            print(f'    cp -r "{source}" "{target}"')
    else:
        print("\nCould not auto-detect Fusion 360 add-ins folder.")
        print("To install the add-in manually:")
        print("  1. Open Fusion 360")
        print('  2. Go to Tools > Add-Ins > Scripts and Add-Ins')
        print('  3. Click the green "+" in My Add-Ins')
        print(f"  4. Browse to: {WORKSPACE / 'MCPserve'}")
        print("  5. Click Open, select it, and click Run")

    print(f"\nAfter installing the add-in:")
    print(f"  1. Start Fusion 360 and run the MCPserve add-in")
    print(f"  2. In a terminal, run: python mcp_server.py")
    print(f"  3. Connect your AI assistant to http://127.0.0.1:3000/sse")


def main():
    print("=" * 60)
    print("Fusion 360 MCP Server - Setup")
    print("=" * 60)
    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"Python:   {sys.executable} ({sys.version.split()[0]})")
    print()

    print("STEP 1: Setting up virtual environment...")
    if not create_venv():
        print("Failed to create virtual environment. Aborting.")
        return

    print("\nSTEP 2: Installing MCP packages...")
    if not install_requirements():
        print("Failed to install packages. Aborting.")
        return

    print("\nSTEP 3: Verifying installation...")
    if not verify_installation():
        print("Verification failed, but packages may still work. Continuing.")

    print_addin_instructions()

    print("\n" + "=" * 60)
    print("Setup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
