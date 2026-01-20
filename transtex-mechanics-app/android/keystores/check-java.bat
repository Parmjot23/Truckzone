@echo off
echo ============================================
echo    Java JDK Verification
echo ============================================
echo.

echo Checking Java installation...
java -version
if %errorlevel% neq 0 (
    echo.
    echo ❌ Java is not installed or not in PATH!
    echo Please install Java JDK 17 from: https://adoptium.net/temurin/releases/
    echo.
    goto :error
)

echo.
echo ✅ Java is installed!
echo.

echo Checking keytool...
keytool -version 2>nul
if %errorlevel% neq 0 (
    echo ❌ keytool is not available!
    echo Make sure JDK bin directory is in your PATH
    echo.
    goto :error
)

echo.
echo ✅ keytool is available!
echo.
echo ============================================
echo    All prerequisites met! 🎉
echo ============================================
echo.
echo You can now run: generate-keystore.bat
echo.
goto :end

:error
echo Please install Java JDK and try again.
echo Run setup-java.bat for installation instructions.

:end
pause
