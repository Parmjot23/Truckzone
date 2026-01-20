# PowerShell script to generate Android keystore for Transtex Mechanics App
Write-Host "Generating Android keystore for Transtex Mechanics App..." -ForegroundColor Green
Write-Host ""

Write-Host "Make sure you have Java JDK installed. If not, download from:" -ForegroundColor Yellow
Write-Host "https://adoptium.net/temurin/releases/" -ForegroundColor Yellow
Write-Host ""

try {
    & keytool -genkeypair -v -storetype PKCS12 -keystore upload-keystore.jks -alias keyalias -keyalg RSA -keysize 2048 -validity 10000 -storepass storepassword -keypass storepassword -dname "CN=Transtex Mechanics, OU=Development, O=Transtex, L=City, ST=State, C=US"

    Write-Host ""
    Write-Host "Keystore generated successfully!" -ForegroundColor Green
    Write-Host "File: upload-keystore.jks" -ForegroundColor Green
    Write-Host ""
    Write-Host "Now you can run: eas build --platform android --profile production" -ForegroundColor Cyan
    Write-Host ""
} catch {
    Write-Host "Error generating keystore. Make sure Java JDK is installed and keytool is in your PATH." -ForegroundColor Red
    Write-Host "Error details: $($_.Exception.Message)" -ForegroundColor Red
}

Read-Host "Press Enter to exit"
