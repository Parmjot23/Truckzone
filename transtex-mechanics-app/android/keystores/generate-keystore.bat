@echo off
echo Generating Android keystore for Transtex Mechanics App...
echo.

echo Make sure you have Java JDK installed. If not, download from:
echo https://adoptium.net/temurin/releases/
echo.

keytool -genkeypair -v -storetype PKCS12 -keystore upload-keystore.jks -alias keyalias -keyalg RSA -keysize 2048 -validity 10000 -storepass storepassword -keypass storepassword -dname "CN=Transtex Mechanics, OU=Development, O=Transtex, L=City, ST=State, C=US"

echo.
echo Keystore generated successfully!
echo File: upload-keystore.jks
echo.
echo Now you can run: eas build --platform android --profile production
echo.

pause
