"""PyInstaller entry point for the Windows service executable."""

from ostium.system.windows_service import main

if __name__ == "__main__":
    main()
