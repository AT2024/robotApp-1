@echo off
echo ===== WINDSURF PROJECT SYNC TOOL =====

REM Path to your shared network folder (using drive letter format)
set SHARED_PATH=P:\Alpha Share\amitai to april\windsurf-git

REM Create folders if they don't exist
if not exist "%SHARED_PATH%\bundles" mkdir "%SHARED_PATH%\bundles"
if not exist "%SHARED_PATH%\logs" mkdir "%SHARED_PATH%\logs"

REM Local temp directory
set LOCAL_TEMP=C:\temp\windsurf_temp
if not exist "%LOCAL_TEMP%" mkdir "%LOCAL_TEMP%"

REM Create timestamp
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list') do set datetime=%%I
set yyyy=%datetime:~0,4%
set mm=%datetime:~4,2%
set dd=%datetime:~6,2%
set hh=%datetime:~8,2%
set min=%datetime:~10,2%
set date_string=%yyyy%-%mm%-%dd%-%hh%%min%

echo.
echo What would you like to do?
echo 1. Create a bundle (after making changes)
echo 2. Apply the latest bundle (to get recent changes)
echo 3. Initialize in current directory (first time setup)
echo.
set /p CHOICE=Enter your choice (1, 2, or 3): 

if "%CHOICE%"=="1" (
    call :create_bundle
) else if "%CHOICE%"=="2" (
    call :apply_bundle
) else if "%CHOICE%"=="3" (
    call :initialize_repo
) else (
    echo Invalid choice. Please enter 1, 2, or 3.
    goto :end
)

goto :end

:create_bundle
    echo.
    echo ===== CREATING BUNDLE =====
    set BUNDLE_NAME=windsurf-%date_string%.bundle
    set LOG_FILE=%SHARED_PATH%\logs\bundle_creation_%date_string%.log

    echo Creating bundle: %BUNDLE_NAME%
    echo This may take a few moments...

    REM Create the Git bundle with all branches
    git bundle create "%SHARED_PATH%\bundles\%BUNDLE_NAME%" --all > "%LOG_FILE%" 2>&1

    REM Check if bundle creation was successful
    if %ERRORLEVEL% EQU 0 (
        echo SUCCESS: Bundle created successfully!
        echo Bundle location: %SHARED_PATH%\bundles\%BUNDLE_NAME%
        
        REM Create a "latest.txt" file to indicate the newest bundle
        echo %BUNDLE_NAME% > "%SHARED_PATH%\bundles\latest.txt"
        echo Marked as latest bundle!
    ) else (
        echo ERROR: Bundle creation failed! Check the log file for details:
        echo %LOG_FILE%
    )
    goto :eof

:initialize_repo
    echo.
    echo ===== INITIALIZING REPOSITORY IN CURRENT DIRECTORY =====
    set LATEST_FILE=%SHARED_PATH%\bundles\latest.txt
    set LOG_FILE=%SHARED_PATH%\logs\repo_init_%date_string%.log

    REM Check if latest.txt exists
    if not exist "%LATEST_FILE%" (
        echo ERROR: Cannot find latest bundle information.
        echo Make sure a bundle has been created first.
        goto :eof
    )

    REM Read the bundle name from latest.txt
    set /p BUNDLE_NAME=<"%LATEST_FILE%"
    set BUNDLE_PATH=%SHARED_PATH%\bundles\%BUNDLE_NAME%

    echo Found latest bundle: %BUNDLE_NAME%

    REM Check if the bundle file exists
    if not exist "%BUNDLE_PATH%" (
        echo ERROR: Bundle file does not exist: %BUNDLE_PATH%
        echo Check network connection or file permissions.
        goto :eof
    )

    echo Copying bundle to local temporary folder...
    if exist "%LOCAL_TEMP%\%BUNDLE_NAME%" del "%LOCAL_TEMP%\%BUNDLE_NAME%"
    copy "%BUNDLE_PATH%" "%LOCAL_TEMP%\%BUNDLE_NAME%" > nul
    
    if not exist "%LOCAL_TEMP%\%BUNDLE_NAME%" (
        echo ERROR: Failed to copy bundle to local temporary folder.
        goto :eof
    )

    echo Initializing Git repository in current directory...
    
    REM Initialize git repository
    git init > "%LOG_FILE%" 2>&1
    
    REM Pull from the local copy of the bundle
    echo Pulling from local bundle copy...
    git pull "%LOCAL_TEMP%\%BUNDLE_NAME%" >> "%LOG_FILE%" 2>&1

    REM Check if the operation was successful
    if %ERRORLEVEL% EQU 0 (
        echo SUCCESS: Repository initialized successfully!
        
        REM Clean up temporary files
        del "%LOCAL_TEMP%\%BUNDLE_NAME%"
        
        REM Now run setup if needed (install dependencies, etc.)
        echo.
        echo Would you like to run the setup script (run.bat) now? (Y/N)
        set /p RUN_SETUP=
        if /i "%RUN_SETUP%"=="Y" (
            echo Running setup script...
            call run.bat
        ) else (
            echo Setup not requested. You can manually run 'run.bat' when ready.
        )
    ) else (
        echo WARNING: Repository initialization failed.
        echo Check the log file for details: %LOG_FILE%
        
        REM Clean up temporary files even on failure
        del "%LOCAL_TEMP%\%BUNDLE_NAME%"
    )
    goto :eof

:apply_bundle
    echo.
    echo ===== APPLYING LATEST BUNDLE =====
    set LATEST_FILE=%SHARED_PATH%\bundles\latest.txt
    set LOG_FILE=%SHARED_PATH%\logs\bundle_update_%date_string%.log

    REM Check if latest.txt exists
    if not exist "%LATEST_FILE%" (
        echo ERROR: Cannot find latest bundle information.
        echo Make sure a bundle has been created first.
        goto :eof
    )

    REM Read the bundle name from latest.txt
    set /p BUNDLE_NAME=<"%LATEST_FILE%"
    set BUNDLE_PATH=%SHARED_PATH%\bundles\%BUNDLE_NAME%

    echo Found latest bundle: %BUNDLE_NAME%

    REM Check if the bundle file exists
    if not exist "%BUNDLE_PATH%" (
        echo ERROR: Bundle file does not exist: %BUNDLE_PATH%
        echo Check network connection or file permissions.
        goto :eof
    )

    echo Copying bundle to local temporary folder...
    if exist "%LOCAL_TEMP%\%BUNDLE_NAME%" del "%LOCAL_TEMP%\%BUNDLE_NAME%"
    copy "%BUNDLE_PATH%" "%LOCAL_TEMP%\%BUNDLE_NAME%" > nul
    
    if not exist "%LOCAL_TEMP%\%BUNDLE_NAME%" (
        echo ERROR: Failed to copy bundle to local temporary folder.
        goto :eof
    )

    echo Updating your local repository...

    REM First time setup - if the repository doesn't exist yet, inform the user
    if not exist ".git" (
        echo Repository not found. Please use option 3 to initialize in this directory.
        del "%LOCAL_TEMP%\%BUNDLE_NAME%"
        goto :eof
    ) else (
        echo Updating existing repository from bundle...
        echo. >> "%LOG_FILE%"
        echo === Fetching updates from bundle === >> "%LOG_FILE%"
        git fetch "%LOCAL_TEMP%\%BUNDLE_NAME%" >> "%LOG_FILE%" 2>&1
        
        REM Get the current branch name
        for /f "tokens=*" %%a in ('git rev-parse --abbrev-ref HEAD') do set CURRENT_BRANCH=%%a
        echo Current branch: %CURRENT_BRANCH% >> "%LOG_FILE%"
        
        REM Try to merge the updates
        echo. >> "%LOG_FILE%"
        echo === Merging updates into current branch === >> "%LOG_FILE%"
        git merge FETCH_HEAD >> "%LOG_FILE%" 2>&1
    )
    
    REM Clean up temporary files
    del "%LOCAL_TEMP%\%BUNDLE_NAME%"

    REM Check if the operation was successful
    if %ERRORLEVEL% EQU 0 (
        echo SUCCESS: Repository updated successfully!
        
        REM Now run setup if needed (install dependencies, etc.)
        echo.
        echo Would you like to run the setup script (run.bat) now? (Y/N)
        set /p RUN_SETUP=
        if /i "%RUN_SETUP%"=="Y" (
            echo Running setup script...
            call run.bat
        ) else (
            echo Setup not requested. You can manually run 'run.bat' when ready.
        )
    ) else (
        echo WARNING: Updates applied but there might be conflicts or issues.
        echo Check the log file for details: %LOG_FILE%
    )
    goto :eof

:end
echo.
echo ================================================
pause