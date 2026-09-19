@echo off
echo NovaClick exe olusturuluyor / Building NovaClick exe...
pip install -r requirements.txt pyinstaller
pyinstaller --noconsole --onefile --clean --icon=novaclick.ico --add-data "novaclick.ico;." --collect-all customtkinter --hidden-import pystray._win32 novaclick.py
echo.
echo Bitti / Done: dist\novaclick.exe
pause
