@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bolsa App
where py >nul 2>nul && (py bolsa_app.py & goto fin)
where python >nul 2>nul && (python bolsa_app.py & goto fin)
echo.
echo No encuentro Python en este PC.
echo Instalalo desde https://www.python.org/downloads/ y marca la casilla "Add python.exe to PATH".
echo Luego vuelve a hacer doble clic en este archivo.
:fin
echo.
pause
