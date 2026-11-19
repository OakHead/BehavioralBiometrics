# Android companion

Native Java app for Android 8.0 and later. This prototype targets Android API 35. It uses a connected-device foreground service, HTTPS long polling with a pinned PC certificate, encrypted pairing storage and notification actions that require unlocking the phone.

See **../Phone_Setup.md** for pairing and use.

## Rebuild on Windows

Requirements: JDK 17 or newer, Android SDK platform 35 and build-tools 35.0.0. Set `JAVA_HOME` to the JDK. The source includes ZXing core 3.5.3 for QR decoding. Its license and notice are included here and in the APK. The build also bundles the Anton and Chakra Petch fonts and their licenses from the desktop assets.

```powershell
python android/build.py --sdk "C:\path\to\Android\Sdk"
```

The script runs AAPT2, javac, D8, zipalign and apksigner. It writes `BehavioralGuard.apk` in the project folder. The Android package ID and signing key stay the same as the preceding release, so updates retain existing app data. The launcher displays **Behavioral Guard**.

The APK signing key is generated once under `data/android-signing`. Keep that directory if you want future APK versions to install as updates. It is excluded from the source ZIP. Do not share its private key or password file.

The APK includes no analytics, ads, cloud service, typed-text collection or mouse recording. Camera access is used only by the QR scanner. It does not save camera images.
