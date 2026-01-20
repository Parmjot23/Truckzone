# Android Keystore Setup

This directory contains the Android upload keystore for the Transtex Mechanics app on Google Play Store.

## 🔧 Prerequisites: Install Java JDK

**You must install Java JDK first before generating the keystore.**

### Windows Installation:
1. **Download JDK 17**: Go to https://adoptium.net/temurin/releases/
2. **Choose**: "Windows x64 MSI Installer" (or x86 if you have 32-bit Windows)
3. **Download and Install** the JDK
4. **Verify Installation**:
   - Open Command Prompt
   - Run: `java -version`
   - Run: `keytool -version`
   - You should see version information for both

### Quick Setup Scripts:
1. **Installation Instructions**: Run `setup-java.bat`
2. **Verify Installation**: Run `check-java.bat`
3. **Generate Keystore**: Run `generate-keystore.bat`

## 🚀 Generate Keystore

After installing Java JDK, run one of these scripts:

### Windows (Command Prompt):
```cmd
cd transtex-mechanics-app\android\keystores
generate-keystore.bat
```

### Windows (PowerShell):
```powershell
cd transtex-mechanics-app\android\keystores
.\generate-keystore.ps1
```

### Manual Generation (if scripts don't work):
```bash
cd transtex-mechanics-app/android/keystores
keytool -genkeypair -v -storetype PKCS12 -keystore upload-keystore.jks -alias keyalias -keyalg RSA -keysize 2048 -validity 10000 -storepass storepassword -keypass storepassword -dname "CN=Transtex Mechanics, OU=Development, O=Transtex, L=City, ST=State, C=US"
```

## 📋 Configuration

Copy `credentials.template.json` to `credentials.json` and update it with your real values:

```bash
cp credentials.template.json credentials.json
```

The keystore is referenced in `credentials.json` with these settings:
- **Key Alias**: `keyalias`
- **Key Password**: `keypassword`
- **Keystore Password**: `storepassword`
- **Keystore Path**: `android/keystores/upload-keystore.jks`
- Ensure the `production` profile in `eas.json` has `"credentialsSource": "local"` so builds use this file.

## ⚠️ Important Notes

- **Never commit the actual keystore file** (`upload-keystore.jks`) to git - it's excluded in `.gitignore`
- `credentials.json` is `.gitignore`d so you can safely keep your real passwords outside version control.
- Keep your keystore passwords secure and backed up
- For existing Play Store apps, you MUST use the original keystore with matching fingerprint
- If you lost your original keystore, contact Google Play Store support (may require app recreation)

## 🔧 Build Your App

After setting up the keystore, build your app:

```bash
eas build --platform android --profile production
```

This will generate an AAB file signed with the correct keystore for Play Store upload.
