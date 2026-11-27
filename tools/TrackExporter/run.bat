@echo off
setlocal
rem Run from tools\ARTExtract. Paths are relative to this file, so it works from any current folder.
cd /d "%~dp0"

set ART=..\..\original\.art
set TRACKS=..\..\original\tracks

echo === Track models (textured OBJ + MTL) from GAME.ART ===
rem Add --split for one OBJ per game object, --yup for Y-up axes, --metres for metres.
rem Use Gamel.art instead of GAME.ART if you want that archive.
python track_extract.py "%ART%\GAME.ART" track_models
if errorlevel 1 goto :failed

echo.
echo === Track data tables (.trs .trc .trl .trk .trt) to CSV/JSON ===
python track_data_extract.py "%TRACKS%" track_data
if errorlevel 1 goto :failed

echo.
echo Done: track_models\ and track_data\
pause
exit /b 0

:failed
echo.
echo Something failed - see the message above.
pause
exit /b 1