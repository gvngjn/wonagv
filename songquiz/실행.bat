@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 노래 맞추기 - 연개소문 시트 채우기

if not exist songquiz.py goto nofile
if not exist yeongaesomun.py goto nofile

echo ============================================
echo  1/2  유튜브 뮤직 '좋아요 표시한 음악' 가져오기
echo ============================================
if not exist playlist.csv goto askimport
echo 이미 받아 둔 playlist.csv 가 있어요.
set "R="
set /p "R=좋아요 목록을 다시 받을까요? (y = 다시 받기 / 그냥 Enter = 있는 목록 쓰기): "
if /i not "%R%"=="y" goto step2

:askimport
if exist cookies.txt (
    echo 이 폴더의 cookies.txt 로 로그인해서 가져올게요.
    set "COOKIE=--cookies cookies.txt"
    goto doimport
)
echo 유튜브에 로그인돼 있는 브라우저를 고르세요.
echo   1 = 파이어폭스   2 = 크롬   3 = 엣지
echo   (크롬/엣지는 브라우저를 완전히 끈 상태여야 하고, 그래도 실패할 수 있어요.
echo    그럴 땐 cookies.txt 를 이 폴더에 넣고 다시 실행하세요.)
set "B="
set /p "B=번호 입력 후 Enter (그냥 Enter = 파이어폭스): "
set "COOKIE=--cookies-from-browser firefox"
if "%B%"=="2" set "COOKIE=--cookies-from-browser chrome"
if "%B%"=="3" set "COOKIE=--cookies-from-browser edge"

:doimport
if exist playlist.csv move /y playlist.csv playlist.old.csv >nul
py songquiz.py import liked %COOKIE%
if errorlevel 1 goto fail

echo.
echo playlist.csv 를 만들었어요. 제목/가수가 이상하면 지금 열어서 고치고 저장하세요.

:step2
echo.
echo ============================================
echo  2/2  연개소문 시트에 넣기
echo ============================================
echo 곡이 많으면 쉬운 곡/어려운 곡으로 맵을 나눌 수 있어요.
echo 맵마다 연개소문 폴더를 따로 하나씩 복사해 두고, 이 파일을 맵 수만큼 실행하세요.
set "M="
set /p "M=맵을 몇 개로 나눌까요? (예: 3 / 그냥 Enter = 안 나눔): "
set "PART="
if not defined M goto askfolder
set "N="
set /p "N=이번에 만들 건 몇 번째 맵인가요? (1 = 가장 쉬운 맵): "
if not defined N goto fail
set "PART=--part %N%/%M%"

:askfolder
echo 연개소문 폴더를 이 창으로 끌어다 놓고 Enter 를 누르세요.
set "Y="
set /p "Y=연개소문 폴더: "
if not defined Y goto fail
set "CK="
if exist cookies.txt set "CK=--cookies cookies.txt"
set "C="
set /p "C=지금까지 받아 둔 곡만으로 만들까요? (y = 받아 둔 곡만 / 그냥 Enter = 남은 곡도 받기): "
if /i "%C%"=="y" set "CK=%CK% --cached-only"
echo.
echo 연개소문 다운로더가 지금 유튜브에서 못 받아서, 여기서 곡을 미리 받아 둘게요.
py songquiz.py yeongaesomun %Y% %PART% %CK%
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
