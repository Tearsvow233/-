@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo    BabyCat 一键重打包（最新源码 -^> exe）
echo ============================================
echo.
echo [1/3] 用最新源码打包 dist\BabyCat.exe ...
C:\Users\zhq\.workbuddy\binaries\python\envs\default\Scripts\python.exe -m PyInstaller BabyCat.spec --noconfirm
if %errorlevel% neq 0 (
    echo.
    echo [X] 打包失败！请把上方红色报错发给开发助手。
    pause
    exit /b 1
)
echo.
echo [2/3] 同步 settings.json 到 dist\settings.json ...
copy /y settings.json dist\settings.json >nul
if %errorlevel% neq 0 (
    echo [X] 配置同步失败，请检查 settings.json 是否存在。
    pause
    exit /b 1
)
echo.
echo [3/3] 完成！
echo --------------------------------------------------
echo  新 exe:  %~dp0dist\BabyCat.exe
echo  配置已随附：dist\settings.json（提醒/AI 设置同步）
echo --------------------------------------------------
echo  小提示：如果旧版本正在运行，先退出它再覆盖，否则文件被占用。
pause
