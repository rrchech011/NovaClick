@echo off
echo NovaClick exe olusturuluyor...
pip install -r requirements.txt pyinstaller
pyinstaller --noconsole --onefile --clean --icon=novaclick.ico --add-data "novaclick.ico;." --collect-all customtkinter novaclick.py
echo.
echo Bitti! Exe dosyasi: dist\novaclick.exe
pause
