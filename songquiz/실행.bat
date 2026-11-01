@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 노래 맞추기 - 연개소문 시트 채우기

if not exist songquiz.py goto nofile
if not exist yeongaesomun.py goto nofile

echo ============================================
echo  1/2  유튜브 뮤직 '좋아요 표시한 음악' 가져오기
echo ============================================
echo 유튜브에 로그인돼 있는 브라우저를 고르세요.
echo   1 = 파이어폭스   2 = 크롬   3 = 엣지
set "B="
set /p "B=번호 입력 후 Enter (그냥 Enter = 파이어폭스): "
set "BROWSER=firefox"
if "%B%"=="2" set "BROWSER=chrome"
if "%B%"=="3" set "BROWSER=edge"

if exist playlist.csv move /y playlist.csv playlist.old.csv >nul
py songquiz.py import liked --cookies-from-browser %BROWSER%
if errorlevel 1 goto fail

echo.
echo playlist.csv 를 만들었어요. 제목/가수가 이상하면 지금 열어서 고치고 저장하세요.
echo.
echo ============================================
echo  2/2  연개소문 시트에 넣기
echo ============================================
echo 연개소문 폴더를 이 창으로 끌어다 놓고 Enter 를 누르세요.
set "Y="
set /p "Y=연개소문 폴더: "
if not defined Y goto fail
py songquiz.py yeongaesomun %Y%
if errorlevel 1 goto fail

echo.
echo 끝! 이제 연개소문 Map 폴더에서 worker.bat 실행 후 build.eds 를 실행하세요.
pause
exit /b

:nofile
echo songquiz.py 와 yeongaesomun.py 를 이 파일과 같은 폴더에 넣고 다시 실행하세요.
pause
exit /b

:fail
echo.
echo 실패했어요. 이 창을 캡처해서 보내 주세요.
pause
